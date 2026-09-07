"""Typed configuration.

Everything the arithmetic depends on is loaded from ``config/model.yaml`` and
``config/candidats_2027.yaml`` into frozen dataclasses. Nothing in the model
code carries a default that could silently disagree with the file.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .paths import MODEL_CONFIG, ROSTER_CONFIG


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass(frozen=True)
class ElectionDates:
    premier_tour: dt.date
    second_tour: dt.date
    cloture_candidatures: dt.date

    def field_is_known(self, as_of: dt.date) -> bool:
        """After candidacies close the ballot is a fact, not a forecast."""
        return as_of >= self.cloture_candidatures


@dataclass(frozen=True)
class PollsConfig:
    history_start: dt.date
    grid_days: int


@dataclass(frozen=True)
class LatentConfig:
    rw_sd_per_day_prior: float
    initial_sd: float
    bloc_rw_sd_per_day_prior: float
    fitted_total_rw_sd_per_day: float
    pin_walk_scales: bool = True


@dataclass(frozen=True)
class NestingConfig:
    prior_a: float
    prior_b: float
    pin_singleton_blocs: bool


@dataclass(frozen=True)
class HouseEffectsConfig:
    sd_prior: float


@dataclass(frozen=True)
class ObservationConfig:
    excess_sd_prior: float
    survey_weight_exponent: float
    reference_population: str


@dataclass(frozen=True)
class ElectionDayErrorConfig:
    fitted: bool
    r1_share_error_sd: float
    r2_margin_error_sd: float
    bloc_error_corr: float


@dataclass(frozen=True)
class SecondTourConfig:
    transfer_concentration: float
    rn_transfer_extra_sd: float


@dataclass(frozen=True)
class FieldConfig:
    source: str
    half_life_days: float
    shrinkage_pseudocounts: float
    overrides: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SamplingConfig:
    draws: int
    tune: int
    chains: int
    target_accept: float
    seed: int
    sims_per_draw: int


@dataclass(frozen=True)
class ModelConfig:
    schema_version: int
    election: ElectionDates
    polls: PollsConfig
    latent: LatentConfig
    nesting: NestingConfig
    house_effects: HouseEffectsConfig
    observation: ObservationConfig
    election_day_error: ElectionDayErrorConfig
    second_tour: SecondTourConfig
    field_: FieldConfig
    sampling: SamplingConfig

    @property
    def grid_days(self) -> int:
        return self.polls.grid_days


def load_model_config(path: Path | None = None) -> ModelConfig:
    raw = _load_yaml(path or MODEL_CONFIG)
    e = raw["election"]
    return ModelConfig(
        schema_version=int(raw["schema_version"]),
        election=ElectionDates(
            premier_tour=e["premier_tour"],
            second_tour=e["second_tour"],
            cloture_candidatures=e["cloture_candidatures"],
        ),
        polls=PollsConfig(**raw["polls"]),
        latent=LatentConfig(**raw["latent"]),
        nesting=NestingConfig(**raw["nesting"]),
        house_effects=HouseEffectsConfig(**raw["house_effects"]),
        observation=ObservationConfig(**raw["observation"]),
        election_day_error=ElectionDayErrorConfig(**raw["election_day_error"]),
        second_tour=SecondTourConfig(**raw["second_tour"]),
        field_=FieldConfig(**{**raw["field"], "overrides": raw["field"].get("overrides") or {}}),
        sampling=SamplingConfig(**raw["sampling"]),
    )


# ----------------------------------------------------------------------
# Roster
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Bloc:
    key: str
    nom_fr: str
    nom_en: str
    couleur: str

    def nom(self, lang: str) -> str:
        return self.nom_fr if lang == "fr" else self.nom_en


@dataclass(frozen=True)
class Candidat:
    id: str
    nom: str
    parti: str
    bloc: str


@dataclass(frozen=True)
class Roster:
    blocs: dict[str, Bloc] = field(default_factory=dict)
    candidats: dict[str, Candidat] = field(default_factory=dict)

    def bloc_of(self, candidate_id: str) -> str | None:
        c = self.candidats.get(candidate_id)
        return c.bloc if c else None

    def members(self, bloc: str) -> list[str]:
        return [c.id for c in self.candidats.values() if c.bloc == bloc]

    @property
    def bloc_keys(self) -> list[str]:
        return list(self.blocs)


def load_roster(path: Path | None = None) -> Roster:
    raw = _load_yaml(path or ROSTER_CONFIG)
    blocs = {k: Bloc(key=k, **v) for k, v in raw["blocs"].items()}
    candidats: dict[str, Candidat] = {}
    for cid, v in raw["candidats"].items():
        if v["bloc"] not in blocs:
            # Fail loudly here rather than silently creating a one-member nest,
            # which would change the substitution structure without any error.
            raise ValueError(f"candidate {cid} has unknown bloc {v['bloc']!r}")
        candidats[cid] = Candidat(id=cid, nom=v["nom"], parti=v["parti"], bloc=v["bloc"])
    return Roster(blocs=blocs, candidats=candidats)
