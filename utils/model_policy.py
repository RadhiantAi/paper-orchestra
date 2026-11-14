"""Explicit capabilities, bounded calls and conservative cost reservations."""

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import threading

from utils.run_control import write_json


class ModelPolicyError(RuntimeError):
    pass


_active = None
_run_lock = threading.Lock()


def active_policy():
    return _active


@contextmanager
def use_policy(policy):
    global _active
    if not _run_lock.acquire(blocking=False):
        raise ModelPolicyError(
            "Run one manuscript per process; use separate processes for parallel runs."
        )
    _active = policy
    try:
        yield
    finally:
        _active = None
        _run_lock.release()


class RunPolicy:
    def __init__(self, profiles, max_cost=0, max_calls=80, probe=True):
        self.profiles, self.max_cost, self.max_calls, self.probe = (
            profiles,
            max_cost,
            max_calls,
            probe,
        )
        self.attempts, self.path = [], None
        self.lock = threading.Lock()
        if not math.isfinite(max_cost) or max_cost < 0 or max_calls < 1:
            raise ModelPolicyError(
                "Run limits must be finite and nonnegative; call limit must be positive."
            )
        for profile in profiles.values():
            for key in ("input_usd_per_million", "output_usd_per_million"):
                if (
                    key not in profile
                    or not math.isfinite(profile[key])
                    or profile[key] < 0
                ):
                    raise ModelPolicyError(
                        "Supply nonnegative prices for each configured model."
                    )
            for key in ("max_input_tokens", "max_output_tokens"):
                if type(profile.get(key)) is not int or profile[key] <= 0:
                    raise ModelPolicyError(
                        "Supply positive input and output token limits."
                    )

    @classmethod
    def from_env(cls):
        path = Path(os.getenv("PAPER_MODEL_POLICY", "model-policy.json"))
        if not path.is_file():
            raise ModelPolicyError(
                "Create model-policy.json from model-policy.example.json before running."
            )
        return cls(
            json.loads(path.read_text(encoding="utf-8")),
            float(os.getenv("PAPER_MAX_COST_USD", "0")),
            int(os.getenv("PAPER_MAX_MODEL_CALLS", "80")),
            os.getenv("PAPER_PROBE_MODE", "live") == "live",
        )

    def check_role(self, model, images=False):
        profile = self.profiles.get(model)
        if not profile or not profile.get("text") or not profile.get("json"):
            raise ModelPolicyError(
                f"Declare text and JSON support for {model} in the model policy."
            )
        if images and (
            not profile.get("images")
            or not isinstance(profile.get("max_image_tokens"), int)
            or profile["max_image_tokens"] <= 0
        ):
            raise ModelPolicyError(
                f"Declare image support and a positive per-image token bound for {model}."
            )
        return profile

    def attach(self, folder):
        self.path = Path(folder) / "model_usage.json"
        if self.path.exists():
            self.attempts = json.loads(self.path.read_text(encoding="utf-8"))[
                "attempts"
            ]
        self.save()

    def save(self):
        if self.path:
            write_json(
                self.path,
                {
                    "max_cost_usd": self.max_cost,
                    "max_calls": self.max_calls,
                    "accounted_cost_usd": sum(
                        a["accounted_usd"] for a in self.attempts
                    ),
                    "pricing_basis": "User-supplied estimates; unknown outcomes retain the full reservation.",
                    "attempts": self.attempts,
                },
            )

    def reserve(self, model, parts, system, max_output):
        with self.lock:
            images = sum("data" in p for p in parts)
            profile = self.check_role(model, images > 0)
            upper_input = (
                len((system or "").encode())
                + sum(len(p.get("text", "").encode()) for p in parts)
                + images * profile.get("max_image_tokens", 0)
                + 1024
            )
            if (
                upper_input > profile["max_input_tokens"]
                or max_output > profile["max_output_tokens"]
            ):
                raise ModelPolicyError(
                    "Request exceeds the configured model context or output allowance."
                )
            reservation = (
                profile["max_input_tokens"] * profile["input_usd_per_million"]
                + max_output * profile["output_usd_per_million"]
            ) / 1_000_000
            if (
                len(self.attempts) >= self.max_calls
                or sum(a["accounted_usd"] for a in self.attempts) + reservation
                > self.max_cost + 1e-12
            ):
                raise ModelPolicyError(
                    "Run model-call or estimated spending limit reached. Resume after reviewing model_usage.json."
                )
            self.attempts.append(
                {
                    "model": model,
                    "status": "reserved",
                    "accounted_usd": reservation,
                    "input_tokens": None,
                    "output_tokens": None,
                }
            )
            self.save()
            return len(self.attempts) - 1

    def finish(self, index, usage=None, status="completed"):
        with self.lock:
            entry = self.attempts[index]
            entry["status"] = status
            if usage and all(
                type(usage.get(k)) is int and usage[k] >= 0
                for k in ("input_tokens", "output_tokens")
            ):
                entry.update(usage)
                profile = self.profiles[entry["model"]]
                entry["accounted_usd"] = (
                    usage["input_tokens"] * profile["input_usd_per_million"]
                    + usage["output_tokens"] * profile["output_usd_per_million"]
                ) / 1_000_000
            self.save()
