import os
import sys

sys.path.append(os.path.abspath("."))

from lightning.pytorch.strategies import DDPStrategy
import wandb
from lightning.pytorch.loggers import WandbLogger
import pandas as pd
from lightning.pytorch.callbacks.early_stopping import EarlyStopping
from lightning.pytorch import Trainer
from lightning.pytorch.callbacks import LearningRateMonitor
from dmsensei.core.callbacks import ModelCheckpoint  # , WandbTestLogger
from dmsensei.config import device
from dmsensei import DataModule, create_model
import sys
import os

import torch

# use float32 only
torch.set_default_dtype(torch.float32)

sys.path.append(os.path.abspath("."))

# Train loop
if __name__ == "__main__":
    USE_WANDB = 1
    STRATEGY = "random"

    print("Running on device: {}".format(device))
    if USE_WANDB:
        project = "debugging"
        name = "evoformer-structure"
        wandb_logger = WandbLogger(project=project, name=name)

    # fit loop
    batch_size = 1
    dm = DataModule(
        name=["yack_train"],
        strategy=STRATEGY,
        shuffle_train=False if STRATEGY == "ddp" else True,
        data_type=["structure"],  #
        force_download=False,
        batch_size=batch_size,
        max_len=1024,
        structure_padding_value=0,
        train_split=None,
        external_valid=["yack_valid", "utr", "pri_miRNA", "human_mRNA"],
    )

    model = create_model(
        model="evoformer",
        ntoken=5,
        d_model=64,
        c_z=32,
        d_cnn=64,
        num_blocks=4,
        no_recycles=0,
        dropout=0,
        lr=7e-4,
        weight_decay=0,
        gamma=0.995,
        wandb=USE_WANDB,
    )

    if USE_WANDB:
        wandb_logger.watch(model, log="all")

    trainer = Trainer(
        accelerator=device,
        devices=1,
        strategy=DDPStrategy() if STRATEGY == "ddp" else "auto",
        precision="16-mixed",
        max_epochs=1000,
        log_every_n_steps=1,
        accumulate_grad_batches=32,
        use_distributed_sampler=STRATEGY != "ddp",
        logger=wandb_logger if USE_WANDB else None,
        callbacks=[
            LearningRateMonitor(logging_interval="epoch"),
            ModelCheckpoint(every_n_epoch=1),
        ]
        if USE_WANDB
        else [],
        enable_checkpointing=False,
    )

    # trainer.fit(model, datamodule=dm)
    trainer.test(model, datamodule=dm)

    if USE_WANDB:
        wandb.finish()
