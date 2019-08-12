# -*- coding: utf-8 -*-

"""Implementation of the HolE model."""

import logging
from typing import Optional

import numpy as np
import torch
import torch.autograd
from torch import nn

from ..base import BaseModule
from ...instance_creation_factories import TriplesFactory
from ...typing import OptionalLoss

__all__ = [
    'HolE',
]

log = logging.getLogger(__name__)


class HolE(BaseModule):
    """An implementation of HolE [nickel2016]_.

     This model uses circular correlation to compose subject and object embeddings to afterwards compute the inner
     product with a relation embedding.

    .. seealso::

       - `author's implementation of HolE <https://github.com/mnick/holographic-embeddings>`_
       - `scikit-kge implementation of HolE <https://github.com/mnick/scikit-kge>`_
       - OpenKE `implementation of HolE <https://github.com/thunlp/OpenKE/blob/OpenKE-PyTorch/models/TransE.py>`_
    """

    entity_embedding_max_norm = 1

    def __init__(
            self,
            triples_factory: TriplesFactory,
            entity_embeddings: Optional[nn.Embedding] = None,
            relation_embeddings: Optional[nn.Embedding] = None,
            embedding_dim: int = 200,
            criterion: OptionalLoss = None,
            preferred_device: Optional[str] = None,
            random_seed: Optional[int] = None,
    ) -> None:
        """Initialize the model."""
        if criterion is None:
            criterion = nn.MarginRankingLoss(margin=1., reduction='mean')

        super().__init__(
            triples_factory=triples_factory,
            criterion=criterion,
            embedding_dim=embedding_dim,
            entity_embeddings=entity_embeddings,
            preferred_device=preferred_device,
            random_seed=random_seed,
        )

        self.relation_embeddings = relation_embeddings

        if None in [self.entity_embeddings, self.relation_embeddings]:
            self._init_embeddings()

    def _init_embeddings(self):
        self.entity_embeddings = nn.Embedding(self.num_entities, self.embedding_dim)
        self.relation_embeddings = nn.Embedding(self.num_relations, self.embedding_dim)

        # Initialisation, cf. https://github.com/mnick/scikit-kge/blob/master/skge/param.py#L18-L27
        entity_embeddings_init_bound = 6 / np.sqrt(
            self.entity_embeddings.num_embeddings + self.entity_embeddings.embedding_dim,
        )
        nn.init.uniform_(
            self.entity_embeddings.weight.data,
            a=-entity_embeddings_init_bound,
            b=+entity_embeddings_init_bound,
        )
        relation_embeddings_init_bound = 6 / np.sqrt(
            self.relation_embeddings.num_embeddings + self.relation_embeddings.embedding_dim,
        )
        nn.init.uniform_(
            self.relation_embeddings.weight.data,
            a=-relation_embeddings_init_bound,
            b=+relation_embeddings_init_bound,
        )

    def forward_owa(self, batch: torch.Tensor) -> torch.Tensor:
        """Forward pass for training with the OWA."""
        h = self.entity_embeddings(batch[:, 0])
        r = self.relation_embeddings(batch[:, 1])
        t = self.entity_embeddings(batch[:, 2])

        # Circular correlation of entity embeddings
        # TODO: Explicitly exploit symmetry and set onesided=True
        a_fft = torch.rfft(h, signal_ndim=1, onesided=False)
        b_fft = torch.rfft(t, signal_ndim=1, onesided=False)

        # complex conjugate
        a_fft[:, :, 1] *= -1

        # Hadamard product in frequency domain
        p_fft = a_fft * b_fft

        # inverse real FFT
        composite = torch.irfft(p_fft, signal_ndim=1, onesided=False, signal_sizes=h.shape[1:])

        # inner product with relation embedding
        scores = torch.sum(r * composite, dim=-1, keepdim=True)

        return scores

    def forward_cwa(self, batch: torch.Tensor) -> torch.Tensor:
        """Forward pass using right side (object) prediction for training with the CWA."""
        h = self.entity_embeddings(batch[:, 0])
        r = self.relation_embeddings(batch[:, 1])
        t = self.entity_embeddings.weight

        # TODO: Explicitly exploit symmetry and set onesided=True
        h_fft = torch.rfft(h, signal_ndim=1, onesided=False)
        t_fft = torch.rfft(t, signal_ndim=1, onesided=False)

        # complex conjugate
        h_fft[:, :, 1] *= -1

        # Hadamard product in frequency domain
        p_fft = h_fft[:, None, :, :] * t_fft[None, :, :, :]

        # inverse real FFT
        composite = torch.irfft(p_fft, signal_ndim=1, onesided=False, signal_sizes=(self.embedding_dim,))

        # inner product with relation embedding
        scores = torch.sum(r[:, None, :] * composite, dim=-1)

        return scores

    def forward_inverse_cwa(self, batch: torch.Tensor) -> torch.Tensor:
        """Forward pass using left side (subject) prediction for training with the CWA."""
        h = self.entity_embeddings.weight
        r = self.relation_embeddings(batch[:, 0])
        t = self.entity_embeddings(batch[:, 1])

        # TODO: Explicitly exploit symmetry and set onesided=True
        h_fft = torch.rfft(h, signal_ndim=1, onesided=False)
        t_fft = torch.rfft(t, signal_ndim=1, onesided=False)

        # complex conjugate
        h_fft[:, :, 1] *= -1

        # Hadamard product in frequency domain
        p_fft = h_fft[None, :, :, :] * t_fft[:, None, :, :]

        # inverse real FFT
        composite = torch.irfft(p_fft, signal_ndim=1, onesided=False, signal_sizes=(self.embedding_dim,))

        # inner product with relation embedding
        scores = torch.sum(r[:, None, :] * composite, dim=-1)

        return scores
