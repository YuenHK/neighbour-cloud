"""Shared image-review value; importing it never loads a local vision engine.

The value has the same provenance semantics as the original in-process class.
It is not an upload/authentication interface or proof of resident consent.
Only the existing masking/approval workflow creates it for actual photo review.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovedPhoto:
    jpeg: bytes
    source_sha256: str
    preview_sha256: str
