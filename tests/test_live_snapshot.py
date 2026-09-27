"""Live / custom-snapshot runs locate scoring files through the ACTIVE source, never the bundled snapshot.

No network: the PGS Catalog REST source and the FTP download are replaced by in-process fakes.
"""

from __future__ import annotations

import gzip
import json

from prsguard import catalog
from prsguard.clawbio_env import REPO_ROOT
from prsguard.pipeline import _scoring

PID = "PGS999998"  # not in the bundled snapshot
URL = "https://ftp.example.invalid/pub/PGS999998_hmPOS_GRCh37.txt.gz"
BUNDLED = REPO_ROOT / "data" / "catalog_snapshot"
SCORING = ("###PGS CATALOG SCORING FILE - SYNTHETIC TEST\n#pgs_id=PGS999998\n"
           "rsID\tchr_name\tchr_position\teffect_allele\tother_allele\teffect_weight\thm_rsID\thm_chr\thm_pos\n"
           "rs1\t1\t100\tA\tG\t0.5\trs1\t1\t100\n")


class FakeLive:
    api_base, catalog_release, api_version = "https://www.pgscatalog.org/rest", "2026-09-17", "test"

    def __init__(self):
        self.calls = []

    def fetch(self, endpoint, params=None, *, url=None, page=1, pgs_id=None, trait_id=None):
        self.calls.append(endpoint)
        if endpoint != f"score/{PID}":
            raise catalog.MetadataUnavailable(f"unexpected {endpoint}")
        body = {"id": PID, "ftp_harmonized_scoring_files": {"GRCh37": {"positions": URL}}}
        return catalog.RawResponse(endpoint, f"{self.api_base}/{endpoint}", json.dumps(body).encode(), "now",
                                   catalog._relpath(endpoint, page, pgs_id, trait_id))


class FakeResp:
    status_code = 200
    content = gzip.compress(SCORING.encode())


def test_custom_snapshot_live_scoring_file_uses_active_source(tmp_path, monkeypatch):
    import requests

    assert not (BUNDLED / PID).exists()
    requested = []
    monkeypatch.setattr(requests, "get", lambda url, **kw: requested.append(url) or FakeResp())
    snap = tmp_path / "custom_snapshot"
    source = catalog.RecordingSource(snap, live=FakeLive())

    score, entry = _scoring(PID, "GRCh37", source)

    assert requested == [URL] and entry["url"] == URL
    assert [v.rsid for v in score.variants] == ["rs1"]
    source.save()
    manifest = json.loads((snap / "SNAPSHOT.json").read_text())["files"]
    assert f"{PID}/{PID}_hmPOS_GRCh37.txt.gz" in manifest and f"{PID}/score.json" in manifest
    assert not (BUNDLED / PID).exists()

    # the custom snapshot now replays offline, with checksum verification
    replay, _ = _scoring(PID, "GRCh37", catalog.SnapshotCatalogSource(snap))
    assert replay.sha256 == score.sha256


def test_snapshot_mode_does_not_fall_back_to_the_bundled_snapshot(tmp_path):
    import pytest

    empty = tmp_path / "empty_snapshot"
    empty.mkdir()
    (empty / "SNAPSHOT.json").write_text(json.dumps({"files": {}}))
    with pytest.raises(catalog.MetadataUnavailable):
        _scoring("PGS000004", "GRCh37", catalog.SnapshotCatalogSource(empty))  # present only in the bundle
