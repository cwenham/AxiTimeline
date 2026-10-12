"""The job hash (interpreter spec, "Job log"): what it covers, and what it deliberately doesn't."""

import hashlib

import pytest

from libaxitl import layout, parse, parse_date

from axitime.jobhash import job_hash, normalised, preimage, resource_hashes
from axitime.resolver import filesystem_resolver

MAIN = 'timeline start=1900 end=1999 length=1m width=210\ninclude "lib/a.axitl"\nspan "s" 1900-1950 illustration(pics/x.svg)\n'
LIB = 'event "e" 1920\n'
PIC = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><path d="M0 0 L5 5"/></svg>\n'


@pytest.fixture
def job(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "pics").mkdir()
    (tmp_path / "main.axitl").write_text(MAIN)
    (tmp_path / "lib" / "a.axitl").write_text(LIB)
    (tmp_path / "pics" / "x.svg").write_text(PIC)
    return tmp_path


def hash_of(path: str, now=None) -> tuple[str, bytes]:
    with open(path) as f:
        result = parse(f.read(), filesystem_resolver, path)
    resolved = layout(result.document, parse_date(now) if now else None)
    return job_hash(result, resolved, path), preimage(result, resolved, path)


def test_preimage_format(job):
    digest, text = hash_of(str(job / "main.axitl"))
    head, _, source = text.partition(b"\nsource ")
    lines = head.decode().splitlines()
    pic = hashlib.sha256(PIC.encode()).hexdigest()
    assert lines == ["axitimeline-job 1", "libaxitl 0.1.0", "axitime 0.1.0", f"resource illustration {pic} pics/x.svg"]
    length, _, flattened = source.partition(b"\n")
    assert int(length) == len(flattened) and flattened.startswith(b"timeline ")
    assert digest == hashlib.sha256(text).hexdigest() and len(digest) == 64


def test_the_hash_doesnt_depend_on_where_axitime_runs(job, monkeypatch):
    monkeypatch.chdir(job)
    here = hash_of("main.axitl")[0]
    monkeypatch.chdir(job.parent)
    assert hash_of(f"{job.name}/main.axitl")[0] == here
    assert hash_of(str(job / "main.axitl"))[0] == here


def test_what_changes_the_hash(job):
    path = str(job / "main.axitl")
    before = hash_of(path)[0]
    (job / "pics" / "x.svg").write_text(PIC.replace("L5 5", "L6 6"))
    assert hash_of(path)[0] != before  # an illustration's content
    (job / "pics" / "x.svg").write_text(PIC)
    (job / "lib" / "a.axitl").write_text(LIB.replace("1920", "1921"))
    assert hash_of(path)[0] != before  # an include's content, through the flattened text
    (job / "lib" / "a.axitl").write_text(LIB)
    assert hash_of(path)[0] == before


def test_what_doesnt(job):
    path = str(job / "main.axitl")
    before = hash_of(path)[0]
    (job / "main.axitl").write_text("// a comment\n" + MAIN.replace("span ", "span   "))
    assert hash_of(path)[0] == before  # comments and spacing don't change what's drawn
    (job / "pics" / "x.svg").write_bytes(b"\xef\xbb\xbf" + PIC.replace("\n", "\r\n").encode())
    assert hash_of(path)[0] == before  # nor a Windows checkout of the same illustration


def test_now_is_part_of_the_hash_only_when_used(job):
    (job / "main.axitl").write_text(MAIN.replace("end=1999", "end=now"))
    path = str(job / "main.axitl")
    a, text = hash_of(path, now="2026-10-12")
    assert b"\nnow 2026\n" in text
    assert hash_of(path, now="2027-01-01")[0] != a
    assert hash_of(path, now="2026-12-31")[0] == a  # the same year: the same layout
    (job / "main.axitl").write_text(MAIN)
    assert b"\nnow " not in hash_of(path, now="2026-10-12")[1]  # supplied but not used: not hashed


def test_resource_hashes_include_includes_for_the_job_log(job):
    path = str(job / "main.axitl")
    with open(path) as f:
        result = parse(f.read(), filesystem_resolver, path)
    assert [(r.kind, r.path) for r in resource_hashes(result, path)] == [
        ("illustration", "pics/x.svg"),
        ("include", "lib/a.axitl"),
    ]


def test_normalised():
    assert normalised(b"\xef\xbb\xbfa\r\nb\rc\n") == b"a\nb\nc\n"
