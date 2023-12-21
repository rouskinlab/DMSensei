from torch import nn
import torch
from ..config import DEFAULT_FORMAT, UKN, seq2int, int2seq

NUM_BASES = len(set(seq2int.values()))


def sequence_to_int(sequence: str):
    return torch.tensor([seq2int[s] for s in sequence], dtype=torch.int64)


def int_to_sequence(sequence: torch.tensor):
    return "".join([int2seq[i.item()] for i in sequence])


def sequence_to_one_hot(sequence_batch: torch.tensor):
    """Converts a sequence to a one-hot encoding"""
    return nn.functional.one_hot(sequence_batch, NUM_BASES).type(DEFAULT_FORMAT)


def base_pairs_to_pairing_matrix(base_pairs, sequence_length, padding, pad_value=UKN):
    pairing_matrix = torch.ones((padding, padding)) * pad_value
    if base_pairs is None:
        return pairing_matrix
    pairing_matrix[:sequence_length, :sequence_length] = 0.0
    if len(base_pairs) > 0:
        pairing_matrix[base_pairs[:, 0], base_pairs[:, 1]] = 1.0
        pairing_matrix[base_pairs[:, 1], base_pairs[:, 0]] = 1.0
    return pairing_matrix


def pairing_matrix_to_base_pairs(pairing_matrix):
    pairing_matrix = pairing_matrix + 1  # Convert to 1-indexed
    base_pairs = []
    for i in range(pairing_matrix.shape[0]):
        for j in range(pairing_matrix.shape[1]):
            if pairing_matrix[i, j] == 1:
                base_pairs.append([i, j])
                pairing_matrix[j, i] = 0
    return base_pairs
