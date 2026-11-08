# tests/test_snapshot_paging.py
"""The cursor paging in clients.snapshot.iter_all_votes, against a fake Snapshot server."""

import logging
import re

import clients.snapshot as snapshot


def fake_server(votes):
    """Answers vote queries the way Snapshot does: created >= cursor, oldest first, `first` at most."""
    def run(query):
        first = int(re.search(r"first: (\d+)", query).group(1))
        since = int(re.search(r"created_gte: (\d+)", query).group(1))
        return {"votes": [v for v in votes if v["created"] >= since][:first]}
    return run


def make_votes(n, per_second=1, start=1_000):
    """n votes; `per_second` of them share each timestamp."""
    return [{"voter": f"0x{i:040x}", "created": start + i // per_second, "choice": 1, "vp": 1.0}
            for i in range(n)]


def fetch(monkeypatch, votes, **kwargs):
    monkeypatch.setattr(snapshot, "_run_query_retry", fake_server(votes))
    return list(snapshot.iter_all_votes("0xproposal", pause=0, **kwargs))


def test_gets_every_vote_past_the_6000_skip_limit(monkeypatch):
    votes = make_votes(7_500)
    got = fetch(monkeypatch, votes)
    assert len(got) == 7_500
    assert len({v["voter"] for v in got}) == 7_500


def test_no_vote_lost_or_repeated_when_a_second_spans_page_boundaries(monkeypatch):
    # 7 votes per second: page edges (1000, 2000) fall in the middle of a second
    votes = make_votes(2_500, per_second=7)
    got = fetch(monkeypatch, votes)
    assert sorted(v["voter"] for v in got) == sorted(v["voter"] for v in votes)


def test_resumes_from_start_ts(monkeypatch):
    votes = make_votes(100)                     # created 1000..1099
    got = fetch(monkeypatch, votes, start_ts=1_090)
    assert [v["created"] for v in got] == list(range(1_090, 1_100))


def test_stops_with_a_warning_instead_of_looping_when_one_second_overflows(monkeypatch, caplog):
    votes = make_votes(1_500, per_second=1_500)   # all 1500 votes in the same second
    with caplog.at_level(logging.WARNING, logger="clients.snapshot"):
        got = fetch(monkeypatch, votes)
    assert len(got) == 1_000                      # capped by the page size, honestly reported
    assert "share timestamp" in caplog.text


def test_empty_proposal_yields_nothing(monkeypatch):
    assert fetch(monkeypatch, []) == []
