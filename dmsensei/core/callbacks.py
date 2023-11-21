from typing import Any
import lightning.pytorch as pl
from lightning.pytorch.utilities.types import STEP_OUTPUT
import torch
import numpy as np
from torch import Tensor, tensor
import wandb
from .metrics import f1, r2_score
from .visualisation import plot_factory
# from lightning.pytorch.utilities import _zero_only
import os
import pandas as pd
from rouskinhf import int2seq
import plotly.graph_objects as go
from lightning.pytorch.utilities import rank_zero_only

from ..config import (
    TEST_SETS_NAMES,
    REF_METRIC_SIGN,
    REFERENCE_METRIC,
    DATA_TYPES,
    POSSIBLE_METRICS,
)
from .metrics import metric_factory

from ..core.datamodule import DataModule
from . import metrics
from .loader import Loader
from os.path import join
from .logger import Logger
from ..util.stack import Stack
import pandas as pd
from lightning.pytorch import Trainer
from lightning.pytorch import LightningModule
from kaggle.api.kaggle_api_extended import KaggleApi
import pickle
from .batch import Batch
from .listofdatapoints import ListOfDatapoints


class MyWandbLogger(pl.Callback):
    def __init__(
        self,
        dm: DataModule,
        model: LightningModule,
        batch_size: int,
        n_best_worst: int = 10,
        wandb_log: bool = True,
    ):
        # init
        self.wandb_log = wandb_log
        self.dm = dm
        self.data_type = dm.data_type
        self.model = model
        self.batch_size = batch_size

        # validation
        # TODO: #12 the validation examples aren't in the validation set
        # self.validation_examples_refs = dm.find_one_reference_per_data_type(
        #     dataset_name="valid"
        # )
        self.val_losses = []
        self.batch_scores = {}
        self.best_score = {d: -torch.inf * REF_METRIC_SIGN[d] for d in self.data_type}
        self.validation_examples_references = {
            data_type: None for data_type in self.data_type
        }
        # testing
        self.n_best_worst = n_best_worst
        self.test_stacks = [{d: [] for d in self.data_type} for _ in TEST_SETS_NAMES]

        self.test_start_buffer = [
            {d: [] for d in self.data_type} for _ in TEST_SETS_NAMES
        ]

    def on_train_batch_end(
        self,
        trainer: Trainer,
        pl_module: LightningModule,
        outputs,
        batch: Any,
        batch_idx: int,
    ) -> None:
        loss = outputs["loss"]
        logger = Logger(pl_module, self.batch_size)
        logger.train_loss(torch.sqrt(loss).item())

    def on_train_end(self, trainer: Trainer, pl_module: LightningModule) -> None:
        pass
    
    def on_validation_batch_end(
        self,
        trainer,
        pl_module,
        outputs,
        batch: Batch,
        batch_idx,
        dataloader_idx=0,
    ):
        logger = Logger(pl_module, self.batch_size)
        
        ### LOG ###
        # Log loss to Wandb
        loss = outputs
        logger.valid_loss(torch.sqrt(loss).item(), isLQ=dataloader_idx)
        
        metrics = compute_error_metrics_pack(batch)
        for data_type, data in metrics.items():
            for metric, score in data.items():
                if metric == REFERENCE_METRIC[data_type]:
                    if data_type not in self.batch_scores:
                        self.batch_scores[data_type] = []
                    self.batch_scores[data_type].append(score)
                
                if not dataloader_idx:
                    logger.log(
                        stage="valid",
                        metric=metric,
                        value=score,
                        data_type=data_type,
                    )
            
        # if not dataloader_idx:
        #     logger.error_metrics_pack('valid', batch)
                        
        if not rank_zero_only.rank == 0 or dataloader_idx !=0:
            return

        # ### END LOG ###

        # #### PLOT ####
        # plot one example per epoch and per data_type
        # initialisation: choose one reference per data_type
        for data_type in self.data_type:
            if self.validation_examples_references[data_type] is None:
                for dp in self.dm.val_set:
                    if dp.contains(data_type):
                        self.validation_examples_references[data_type] = dp.get(
                            "reference"
                        )
                        break
        # plot the examples
        for data_type, name in plot_factory.keys():
            if batch.contains(data_type) and self.validation_examples_references[
                data_type
            ] in set(batch.get("reference")):
                idx = batch.get("reference").index(
                    self.validation_examples_references[data_type]
                )
                pred, true = batch.get(data_type, pred=True, true=True, index=idx)
                plot = plot_factory[(data_type, name)](
                    pred=pred,
                    true=true,
                    sequence=batch.get("sequence", index=idx),
                    reference=batch.get("reference", index=idx),
                    length=batch.get("length", index=idx),
                )
                logger.valid_plot(data_type, name, plot)
        #### END PLOT ####

    def on_validation_end(self, trainer:Trainer, pl_module, dataloader_idx=0):
        
        # logger = Logger(pl_module, self.batch_size)
        
        # to_log = {}
        # for data_type, data in self.batch_scores.items():
        #     for metric, scores in data.items():
        #         trainer.logger.log(
        #             stage="valid",
        #             metric=metric,
        #             value=np.nanmean(scores),
        #             data_type=data_type,
        #         )
        
        if not rank_zero_only.rank == 0:
            return
        
        # Save best model
        loader = Loader()
        for data_type, scores in self.batch_scores.items():
            # if best metric, save metric as best
            average_score = np.nanmean(scores)
            # The definition of best depends on the metric
            if (
                average_score * REF_METRIC_SIGN[data_type]
                > self.best_score[data_type] * REF_METRIC_SIGN[data_type]
            ):
                self.best_score[data_type] = average_score

                # save model for the best r2
                if (
                    data_type == "dms" and rank_zero_only.rank == 0
                ):  # only keep best model for dms
                    loader.dump(self.model)

        self.batch_scores = {}

    def on_test_start(self, trainer, pl_module):
        # init loggers 
        
        if not self.wandb_log or rank_zero_only.rank != 0:
            return

        # Load best model for testing
        loader = Loader()
        weights = loader.load_from_weights(safe_load=True)
        if weights is not None:
            pl_module.load_state_dict(weights)

    def on_test_batch_end(
        self, trainer, pl_module, outputs, batch: Batch, batch_idx, dataloader_idx=0
    ):
        logger = Logger(pl_module, batch_size=self.batch_size)

        # compute scores
        list_of_datapoints = batch.to_list_of_datapoints()
        for dp in list_of_datapoints:
            dp.compute_error_metrics_pack()
            # stack scores
            for data_type in dp.metrics.keys():
                self.test_stacks[dataloader_idx][data_type].append(
                    (dp.get('reference'), dp.read_reference_metric(data_type))
                )

        # Logging metrics to Wandb
        logger.error_metrics_pack(
            "test/{}".format(TEST_SETS_NAMES[dataloader_idx]), list_of_datapoints
        )

    def on_test_end(self, trainer, pl_module):
        logger = Logger(pl_module, batch_size=self.batch_size)
        
        if not self.wandb_log or rank_zero_only.rank != 0:
            return

        for dataloader_idx in range(len(TEST_SETS_NAMES)):
            for data_type in self.data_type:
                
                # stack the scores together and sort them
                df = pd.DataFrame(self.test_stacks[dataloader_idx][data_type], columns=["reference", "score"])
                if not len(df):
                    continue
                df.sort_values(by="score", inplace=True, ascending=REF_METRIC_SIGN[data_type] < 0)
                mid_score = df["score"].values[len(df) // 2]
                
                # only keep the best and worst examples
                refs = set(df["reference"].values[:self.n_best_worst]).union(
                    set(df["reference"].values[-self.n_best_worst:])
                )
                df.set_index("reference", inplace=True)
                 
                # retrieve datapoints in the test set
                list_of_datapoints = ListOfDatapoints()
                for dp in self.dm.test_sets[dataloader_idx]:
                    if dp.get('reference') in refs:  
                        list_of_datapoints = list_of_datapoints + dp #lowkey flex on the __add__ method
                        
                # compute predictions
                batch = Batch.from_list_of_datapoints(list_of_datapoints, ['sequence', data_type])
                prediction = pl_module(batch.get('sequence'))
                batch.integrate_prediction(prediction)

                # plot the examples and log them into wandb
                for dp in batch.to_list_of_datapoints():   
                    for plot_data_type, plot_name in plot_factory.keys():
                        if plot_data_type != data_type:
                            continue
                        
                        # generate plot
                        plot = plot_factory[(plot_data_type, plot_name)](
                            pred=dp.get(plot_data_type, pred=True, true=False),
                            true=dp.get(plot_data_type, pred=False, true=True),
                            sequence=dp.get("sequence"),
                            reference=dp.get("reference"),
                            length=dp.get("length"),
                        )  # add arguments here if you want
                        
                        # log plot
                        logger.test_plot(
                            dataloader=TEST_SETS_NAMES[dataloader_idx],
                            data_type=data_type,
                            name=plot_name + "_" + ('best' if df.loc[dp.get('reference'), 'score'] > mid_score else 'worst'),
                            plot=plot,
                        )


class KaggleLogger(pl.Callback):
    def __init__(self, dm: DataModule, push_to_kaggle=True) -> None:
        # prediction
        self.predictions = [None] * len(dm.predict_set)
        self.predictions_idx = 0
        self.dm = dm
        self.push_to_kaggle = push_to_kaggle

    def on_predict_start(self, trainer, pl_module):
        if wandb.run is None:
            return
        
        loader = Loader()
        # Load best model for testing
        weights = loader.load_from_weights(safe_load=True)
        if weights is not None:
            pl_module.load_state_dict(weights)

    def on_predict_batch_end(
        self,
        trainer: Trainer,
        pl_module: LightningModule,
        outputs: Any,
        batch: Batch,
        batch_idx: int,
        dataloader_idx: int = 0,
    ) -> None:
        for dp in batch.to_list_of_datapoints():
            self.predictions[self.predictions_idx] = {"reference": dp.get("reference")}
            for dt in self.dm.data_type:
                self.predictions[self.predictions_idx][dt] = dp.get(
                    dt, pred=True, true=False, to_numpy=True
                )
            self.predictions_idx += 1

    def on_predict_end(self, trainer, pl_module):
        # load data
        df = pd.DataFrame(self.predictions)

        sequence_ids = pd.read_csv(
            os.path.join(
                os.path.dirname(__file__), "../resources/test_sequences_ids.csv"
            )
        )
        df = pd.merge(sequence_ids, df, on="reference")

        # save predictions as csv
        dms = np.concatenate(df["dms"].values)
        shape = np.concatenate(df["shape"].values)
        dms, shape = np.clip(dms, 0, 1), np.clip(shape, 0, 1)
        pd.DataFrame(
            {"reactivity_DMS_MaP": dms, "reactivity_2A3_MaP": shape}
        ).reset_index().rename(columns={"index": "id"}).to_csv(
            "predictions.csv", index=False
        )

        # save predictions as pickle
        pickle.dump(df, open("predictions.pkl", "wb"))
        
        # compress predictions
        os.system("zip predictions.csv.zip predictions.csv")

        # upload to kaggle
        if self.push_to_kaggle:
            api = KaggleApi()
            api.authenticate()
            api.competition_submit(
                file_name="predictions.csv.zip",
                message="from predict callback" if not hasattr(pl_module, 'kaggle_message') else pl_module.kaggle_message,
                competition="stanford-ribonanza-rna-folding",
            )


class ModelChecker(pl.Callback):
    def __init__(self, model, log_every_nstep=1000):
        self.step_number = 0
        self.model = model
        self.log_every_nstep = log_every_nstep

    def on_train_batch_end(self, trainer, pl_module, outputs, batch, batch_idx):
        if self.step_number % self.log_every_nstep == 0:
            # Get all parameters
            params = []
            for param in pl_module.parameters():
                params.append(param.view(-1))
            params = torch.cat(params).cpu().detach().numpy()

            # Compute histogram
            if rank_zero_only.rank == 0 and self.model in ["mlp"]:
                wandb.log({"model_params": wandb.Histogram(params)})

        self.step_number += 1


def compute_error_metrics_pack(batch: Batch):
    pred, true = batch.get_pairs("dms")
    return {
        data_type: {
            metric_name: metric_factory[metric_name](
                pred=pred,
                true=true,
                batch=len(batch.get_index(data_type)) > 1,
            )
            for metric_name in POSSIBLE_METRICS[data_type]
        }
        for data_type in DATA_TYPES
        if batch.contains(data_type)
    }
