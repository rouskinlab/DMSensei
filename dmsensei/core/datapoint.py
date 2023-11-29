from typing import Any
import numpy as np
from ..config import DATA_TYPES, POSSIBLE_METRICS, device
import numpy as np
import torch.nn.functional as F
from .metrics import metric_factory
from ..util import unzip
import torch
from .embeddings import sequence_to_int
from .datatype import *

from dmsensei.config import UKN, DATA_TYPES, DATA_TYPES_FORMAT
from dmsensei.core.embeddings import sequence_to_int
import torch
from torch import tensor


def split_data_type(data_type):
    if not "_" in data_type:
        data_part = "true"
    else:
        data_part, data_type = data_type.split("_")
    return data_part, data_type


class Datapoint:
    def __init__(
        self,
        reference: str,
        sequence: str,
        dms: DMSDatapoint = None,
        shape: SHAPEDatapoint = None,
        structure: StructureDatapoint = None,
    ):
        self.reference = reference
        self.sequence = sequence_to_int(sequence) if type(sequence) == str else sequence
        self.length = len(sequence)
        self.dms = dms
        self.shape = shape
        self.structure = structure
        self.data_types = [
            attr
            for attr in ["dms", "shape", "structure"]
            if getattr(self, attr) is not None
        ]

    def to(self, device):
        self.sequence = self.sequence.to(device)
        for attr in self.data_types:
            if hasattr(getattr(self, attr), "to"):
                getattr(self, attr).to(device)
        return self
    

    @classmethod
    def from_data_json_line(cls, line: dict):
        ref, values = line
        seq = values["sequence"]
        data = {}
        for data_type in DATA_TYPES:
            if data_type in values and not (values[data_type] is None or (type(values[data_type]) == float and np.isnan(values[data_type]))):
                data[data_type] = data_type_factory['datapoint'][data_type](
                    true=tensor(values[data_type], dtype=DATA_TYPES_FORMAT[data_type]),
                    error=tensor(
                        values["error_" + data_type], dtype=DATA_TYPES_FORMAT[data_type]
                    )
                    if "error_" + data_type in values
                    else None,
                    quality=values["quality_" + data_type]
                    if "quality_" + data_type in values
                    else None,
                )
        return cls(ref, seq, **data).to(device)

    def add_prediction(self, preds: dict):
        for data_type, value in preds.items():
            getattr(self, data_type).pred = value

    def get(self, data_type, to_numpy=False):
        if data_type in ["reference", "sequence", "length"]:
            return getattr(self, data_type)
        data_part, data_type = split_data_type(data_type)

        if not data_type in self.data_types:
            raise ValueError(f"This datapoints doesn't contain data type {data_type}.")
        out = getattr(getattr(self, data_type), data_part)

        if to_numpy:
            if hasattr(out, "cpu"):
                out = out.squeeze().cpu().numpy()
        return out

    def contains(self, data_type):
        data_part, data_type = split_data_type(data_type)
        if getattr(self, data_type) is None:
            return False
        return getattr(getattr(self, data_type), data_part) != None

    def compute_error_metrics_pack(self):
        self.metrics = {}
        for data_type in self.data_types:
            if not (
                self.contains(f"true_{data_type}")
                and self.contains(f"pred_{data_type}")
            ):
                continue
            pred = self.get(f"pred_{data_type}")
            true = self.get(f"true_{data_type}")
            self.metrics[data_type] = {}
            for metric_name in POSSIBLE_METRICS[data_type]:
                self.metrics[data_type][metric_name] = metric_factory[metric_name](
                    true=true, pred=pred, batch=False
                )
        return self.metrics
