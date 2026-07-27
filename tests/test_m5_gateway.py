import asyncio

import pytest
from pydantic import Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBModelCall
from app.m2_contracts import StrictModel
from app.m5_capabilities import Capability, CapabilityContract, M5CapabilityError
from app.m5_gateway import GatewayRequest, M5ModelGateway, ModelRegistration, PromptSpec


class Answer(StrictModel):
    summary: str = Field(min_length=1)


class Backend:
    def __init__(self, output):
        self.output = output

    async def generate(self, system_prompt, user_prompt, *, role):
        return self.output


class FailingBackend:
    async def generate(self, system_prompt, user_prompt, *, role):
        raise ValueError("provider payload failed")


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _request():
    return GatewayRequest(
        contract=CapabilityContract(capability=Capability.ANSWER, idempotency_key="m5-gateway-001"),
        prompt=PromptSpec(key="answer", version="1.0", system_prompt="Answer from supplied context only."),
        user_prompt="Explain recall.",
    )


def _registration(**updates):
    data = dict(
        registration_version="1", provider="test", model="test-json", tier="fast",
        capabilities=(Capability.ANSWER,), supports_json=True, context_length=8192,
        input_cost_per_million=1.0, output_cost_per_million=2.0,
    )
    data.update(updates)
    return ModelRegistration(**data)


def test_m5_gateway_persists_trace_without_raw_prompt_and_validates_json():
    session = _session()
    result = asyncio.run(M5ModelGateway().execute(
        session,
        request=_request(),
        registration=_registration(),
        backend=Backend('{"summary":"Recall measures relevant items found."}'),
        response_model=Answer,
    ))
    row = session.query(DBModelCall).one()
    assert result.status == "completed"
    assert result.structured_output["summary"].startswith("Recall")
    assert row.prompt_version == "answer:1.0"
    assert row.input_summary["user_prompt_chars"] == len("Explain recall.")
    assert "Explain recall" not in str(row.input_summary)
    assert len(row.output_hash) == 64


def test_m5_gateway_records_schema_failure_as_terminal_result():
    session = _session()
    with pytest.raises(M5CapabilityError, match="strict schema"):
        asyncio.run(M5ModelGateway().execute(
            session,
            request=_request(),
            registration=_registration(),
            backend=Backend("not-json"),
            response_model=Answer,
        ))
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "structured_output_invalid")


def test_m5_gateway_does_not_misclassify_provider_value_errors():
    session = _session()
    with pytest.raises(M5CapabilityError, match="provider call failed"):
        asyncio.run(M5ModelGateway().execute(
            session,
            request=_request(),
            registration=_registration(),
            backend=FailingBackend(),
            response_model=Answer,
        ))
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "provider_call_failed")
