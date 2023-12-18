import torch
from ..config import UKN
import torch


# wrapper for metrics
def mask_and_flatten(func):
    def wrapped(pred, true):
        mask = true != UKN
        if torch.sum(mask) == 0:
            return None
        pred = pred[mask]
        true = true[mask]
        return func(pred, true)

    return wrapped


@mask_and_flatten
def f1(pred, true, threshold=0.5):
    """
    Compute the F1 score of the predictions.

    :param pred: Predicted pairing matrix probability  (L,L)
    :param true: True binary pairing matrix (L,L)
    :return: F1 score for this RNA structure
    """

    pred = (pred > threshold).float()

    sum_pair = torch.sum(pred) + torch.sum(true)

    if sum_pair == 0:
        return 1.0
    else:
        return (2 * torch.sum(pred * true) / sum_pair).item()


# def mFMI(pred, true, threshold=0.5):
#     """
#     Compute the mFMI score of the predictions.

#     :param pred: Predicted pairing matrix probability  (L,L)
#     :param true: True binary pairing matrix (L,L)
#     :return: mFMI score for this RNA structure
#     """

#     mask = true != UKN
#     pred = pred[mask]
#     true = true[mask]

#     pred = (pred > threshold).float()

#     TP = torch.sum(pred * true)

#     prod_true = torch.sum(pred) * torch.sum(true)
#     if prod_true > 0:
#         FMI = TP / torch.sqrt(prod_true)
#     else:
#         FMI = 0

#     u = (
#         torch.sum((~torch.sum(pred).bool()) * (~torch.sum(true).bool()))
#         / pred.shape[-1]
#     )

#     mFMI = u + (1 - u) * FMI

#     return mFMI.item()


@mask_and_flatten
def r2_score(pred, true):
    """
    Compute the R2 score of the predictions.

    :param true: True values
    :param pred: Predicted values
    :return: R2 score
    """

    return (
        1 - torch.sum((true - pred) ** 2) / torch.sum((true - torch.mean(true)) ** 2)
    ).item()


@mask_and_flatten
def pearson_coefficient(pred, true):
    """
    Compute the Pearson correlation coefficient of the predictions.

    :param true: True values
    :param pred: Predicted values
    :return: pearson coefficient
    """

    return torch.mean(
        (pred - torch.mean(pred))
        * (true - torch.mean(true))
        / (torch.std(pred) * torch.std(true))
    ).item()


@mask_and_flatten
def mae_score(pred, true):
    """
    Compute the Mean Average Error of the predictions.

    :param true: True values
    :param pred: Predicted values
    :return: MAE score
    """

    return torch.mean(torch.abs(true - pred)).item()


metric_factory = {
    "f1": f1,
    "r2": r2_score,
    "pearson": pearson_coefficient,
    "mae": mae_score,
}
