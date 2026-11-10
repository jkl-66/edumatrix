"""Inference must not build a graph during the concept projection stage."""
from types import SimpleNamespace
import math

import pytest
import torch

import bkt_engine
import embedding_models


def test_mastery_prediction_has_no_grad_graph_and_preserves_probabilities(monkeypatch):
    vector=[0.0]*384
    vector[0]=1.0
    monkeypatch.setattr(embedding_models,'EMBEDDINGS',SimpleNamespace(embed=lambda _:vector))
    monkeypatch.setattr(bkt_engine,'CONCEPT_TO_INDEX',{'known':0})

    class Probe(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.concept_embeddings=torch.nn.Embedding.from_pretrained(torch.tensor([vector]),freeze=False)
            self.bilinear=torch.nn.Linear(384,384,bias=False)
            with torch.no_grad():
                self.bilinear.weight.copy_(torch.eye(384))
            self.scale_factor=1.0

        def forward(self,sequence,bias):
            return sequence[:,-1,:384]+bias

    probe=Probe()
    observations=[]
    hooks=[module.register_forward_hook(lambda module,args,output: observations.append(
        (torch.is_grad_enabled(),output.requires_grad)))
        for module in (probe,probe.concept_embeddings,probe.bilinear)]
    service=object.__new__(bkt_engine.DktService)
    service.model=probe
    original={key:value.detach().clone() for key,value in probe.state_dict().items()}
    try:
        with torch.enable_grad():
            result=service.predict_mastery([('known',True)],extra_concepts=['new'])
            assert torch.is_grad_enabled(), 'Inference must restore its caller context'
        expected=1/(1+math.exp(-1))
        assert result==pytest.approx({'known':expected,'new':expected})
        assert len(observations)==4  # RNN substitute, lookup, two concept projections
        assert all(not grad and not requires for grad,requires in observations)
        assert all(torch.equal(original[key],value) for key,value in probe.state_dict().items())
        assert all(parameter.grad is None for parameter in probe.parameters())
    finally:
        for hook in hooks: hook.remove()
