import lightning.pytorch as pl
import torch.nn as nn
import torch
import numpy as np
from ..config import VAL_GU
from rouskinhf import seq2int
import torch.nn.functional as F
from .batch import Batch


class Model(pl.LightningModule):
    def __init__(self, lr: float, optimizer_fn, quality=True, **kwargs):
        super().__init__()

        # Set attributes
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.lr = lr
        self.optimizer_fn = optimizer_fn
        self.automatic_optimization = True
        self.use_quality = quality
        self.save_hyperparameters()

    def configure_optimizers(self):
        optimizer = self.optimizer_fn(
            self.parameters(),
            lr=self.lr,
            weight_decay=self.weight_decay if hasattr(self, "weight_decay") else 0,
        )
        
        if not hasattr(self, "gamma") or self.gamma is None:
            return optimizer
        
        scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=self.gamma)
        return [optimizer], [scheduler]

    def _loss_signal(self, batch: Batch, data_type:str):
        assert data_type in ['dms', 'shape'], "This function only works for dms and shape data"
        pred, true = batch.get_pairs(data_type)
        mask = true != -1000.
        if self.use_quality:
            weights = batch.get_weights_as_matrix(data_type, true.shape[1])
            loss = F.mse_loss(pred[mask], true[mask], reduction="none") @ weights[mask] / len(weights[mask])
            return loss
        return F.mse_loss(pred[mask], true[mask], reduction="mean")
        
    def _loss_structure(self, batch: Batch):
        # Unsure if this is the correct loss function
        pred, true = batch.get("structure")
        if self.use_quality:
            weights = batch.get("quality_structure")[batch.get_index("structure")].unsqueeze(-1)
            return F.binary_cross_entropy(input=pred, target=true, reduction="none") @ weights / len(weights)
        return F.binary_cross_entropy(input=pred, target=true, reduction="mean")
        
    def loss_fn(self, batch: Batch):
        loss = torch.tensor(0.0, device=self.device)
        count = {dt: batch.count(dt) for dt in batch.data_type if batch.contains(dt)}
        if batch.contains("dms"):
            loss += count["dms"] * self._loss_signal(batch, 'dms')
        if batch.contains("shape"):
            loss += count["shape"] * self._loss_signal(batch, 'shape')
        if batch.contains("structure"):
            loss += count["structure"] * self._loss_structure(batch)
        return loss / np.sum(list(count.values()))

    def training_step(self, batch: Batch, batch_idx: int):
        predictions = self.forward(batch.get("sequence"))
        batch.integrate_prediction(predictions)
        loss = self.loss_fn(batch)
        return loss

    def validation_step(self, batch: Batch, batch_idx: int, dataloader_idx=0):
        predictions = self.forward(batch.get("sequence"))
        batch.integrate_prediction(predictions)
        loss = self.loss_fn(batch)
        return loss

    def test_step(self, batch: Batch, batch_idx: int, dataloader_idx=0):
        predictions = self.forward(batch.get("sequence"))
        batch.integrate_prediction(predictions)

    def predict_step(self, batch: Batch, batch_idx: int):
        predictions = self.forward(batch.get("sequence"))
        
        # Hardcoded values for DMS G/U bases
        if "dms" in predictions.keys():
            predictions["dms"][
                (batch.get("sequence") == seq2int["G"])
                | (batch.get("sequence") == seq2int["U"])
            ] = VAL_GU

        # clip values to [0, 1]
        for data_type in set(['dms', 'shape']).intersection(predictions.keys()):
            predictions[data_type] = torch.clip(predictions[data_type], min=0, max=1)

        batch.integrate_prediction(predictions)
