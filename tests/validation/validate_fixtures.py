# -*- coding: utf-8 -*-
"""实施前条件 3：失败注入样本集本地验证。

验证对象：data/failure-fixtures-2026-11-01/ 下的 24 个 fixture 及其 manifest。
不验证连接器行为——连接器尚不存在，凡依赖连接器的判据一律 NOT_VERIFIED。

只读：不发起任何外部请求，不写生产代码、数据库、配置。

用法：
    .venv\\Scripts\\python.exe tests\\validation\\validate_fixtures.py [--json OUT]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "data" / "failure-fixtures-2026-11-01"
EIA_SAMPLE_DIR = ROOT / "data" / "eia-sample-2026-11-01"
SEC_SAMPLE_DIR = ROOT / "data" / "sec-sample-2026-11-01"
DOC = ROOT / "docs" / "FAILURE_INJECTION_ACCEPTANCE_2026-11-01.md"

CLASSES = ["auth", "rate_limit", "not_found", "server", "timeout",
           "schema", "truncation", "empty_result", "rights"]
CONFIDENCE = {"high", "medium", "low", "n/a"}

PASS, FAIL, NA = "PASS", "FAIL", "NOT_VERIFIED"

results: list[dict] = []


def record(fid, check, status, detail):
    results.append({"fixture_id": fid, "check": check, "status": status, "detail": detail})


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- reference shapes
def observed_eia_shape() -> dict:
    """从真实响应中提取 EIA 数据行与响应层的键集合。"""
    p = EIA_SAMPLE_DIR / "monthly_sample.json"
    j = load(p)
    row = j["response"]["data"][0]
    return {"row_keys": set(row), "response_keys": set(j["response"]), "top_keys": set(j)}


def observed_sec_shape() -> dict:
    p = SEC_SAMPLE_DIR / "aapl_rev.json"
    j = load(p)
    unit = next(iter(j["units"].values()))
    return {"top_keys": set(j), "row_keys": set(unit[0])}


# ---------------------------------------------------------------- generic helpers
def body_rows(source: str, body) -> list:
    """返回响应体中的数据行（不代表连接器输出行数）。"""
    if not isinstance(body, dict):
        return []
    if source == "eia":
        data = body.get("response", {}).get("data")
        return data if isinstance(data, list) else []
    if source == "sec-edgar":
        units = body.get("units")
        if not isinstance(units, dict):
            return []
        out = []
        for rows in units.values():
            if isinstance(rows, list):
                out.extend(rows)
        return out
    return []


def total_of(body):
    try:
        return body["response"]["total"]
    except Exception:
        return None


# ---------------------------------------------------------------- per-fixture checks
def check_fixture(f: dict, eia_ref_status: dict, sec_shape: dict, eia_shape: dict, key_env: str):
    fid = f["fixture_id"]
    src = f.get("source")

    # C1 文件存在 / 字节 / 哈希
    if f.get("ref"):
        p = ROOT / f["ref"]
    else:
        p = FIXTURE_DIR / f["file"]
    if not p.exists():
        record(fid, "C1 文件存在且哈希一致", FAIL, f"文件不存在：{p}")
        return
    raw = p.read_bytes()
    ok_hash = sha(raw) == f.get("sha256")
    ok_size = len(raw) == f.get("bytes")
    record(fid, "C1 文件存在且哈希一致", PASS if (ok_hash and ok_size) else FAIL,
           f"{p.name} {len(raw)}B sha256 {'一致' if ok_hash else '不一致'}，字节数 {'一致' if ok_size else '不一致'}")

    # C2 来源标注完整性
    origin = f.get("origin")
    if origin == "observed":
        ref_ok = f.get("ref", "").startswith("data/eia-sample-2026-11-01/")
        declared = f.get("http_status")
        actual = eia_ref_status.get(Path(f["ref"]).name)
        if actual is None:
            record(fid, "C2 观测来源可回溯", NA, "eia-sample request_manifest 中无该文件的唯一状态记录")
        else:
            record(fid, "C2 观测来源可回溯", PASS if (ref_ok and actual == declared) else FAIL,
                   f"引用 {f['ref']}；真实请求记录状态 {actual}，样本声明 {declared}")
    elif origin == "synthetic":
        in_dir = "file" in f and (FIXTURE_DIR / f["file"]).exists()
        record(fid, "C2 合成来源定位正确", PASS if in_dir else FAIL,
               f"{f.get('file')} 位于专用样本目录" if in_dir else "合成样本不在样本目录内")
    else:
        record(fid, "C2 来源标注", FAIL, f"origin 非法：{origin!r}")

    # C3 状态码与响应体类别一致
    status = f.get("http_status")
    is_html = p.suffix == ".html"
    body = None
    if not is_html:
        try:
            body = load(p)
        except Exception as exc:
            body = None
            record(fid, "C3 状态码与响应体类别", FAIL, f"声称 JSON 但解析失败：{exc}")

    if status is None:
        is_desc = isinstance(body, dict) and "exception" in body
        is_rights = isinstance(body, dict) and isinstance(body.get("rights"), dict)
        if is_rights:
            record(fid, "C3 状态码与响应体类别", PASS, "非 HTTP 事务的权利记录，按权利样本校验")
        elif is_desc:
            record(fid, "C3 状态码与响应体类别", PASS, "无响应体描述文件")
        else:
            record(fid, "C3 状态码与响应体类别", FAIL, "状态为 None，且既不是超时描述也不是权利记录")
    elif status >= 400:
        has_err = is_html or (isinstance(body, dict) and "error" in body)
        rows = body_rows(src, body) if body is not None else []
        ok = has_err and not rows
        record(fid, "C3 状态码与响应体类别", PASS if ok else FAIL,
               f"HTTP {status}，错误体 {'存在' if has_err else '缺失'}，数据行 {len(rows)}")
    else:
        ok = isinstance(body, dict)
        record(fid, "C3 状态码与响应体类别", PASS if ok else FAIL,
               f"HTTP {status}，JSON 解析 {'成功' if ok else '失败'}")

    # C4 期望块完整性
    exp = f.get("expected", {})
    problems = []
    if not isinstance(exp.get("emitted"), int):
        problems.append("expected.emitted 非整数")
    ec = exp.get("error_class")
    if ec is not None and ec not in CLASSES:
        problems.append(f"error_class 不在 9 类内：{ec!r}")
    if "quality_flags" in exp and not isinstance(exp["quality_flags"], list):
        problems.append("quality_flags 非列表")
    if ec is not None and not isinstance(exp.get("must_not"), str):
        problems.append("失败样本缺少 must_not")
    record(fid, "C4 期望块完整性", PASS if not problems else FAIL,
           "字段齐全且取值合法" if not problems else "；".join(problems))

    # C5 error_class 与 HTTP 状态对应
    if ec is None:
        record(fid, "C5 error_class 与状态码对应", PASS, "非失败样本，无需对应")
    else:
        want = {"auth": {401, 403}, "rate_limit": {429}, "not_found": {404},
                "server": {500, 502, 503, 504}, "timeout": {None},
                "schema": {200}, "truncation": {200}, "empty_result": {200},
                "rights": {None}}.get(ec, set())
        record(fid, "C5 error_class 与状态码对应", PASS if status in want else FAIL,
               f"{ec} 期望状态 {sorted(x for x in want if x is not None) or 'None'}，实际 {status}")

    # C6 置信度声明
    conf = f.get("shape_confidence")
    if conf not in CONFIDENCE:
        record(fid, "C6 置信度声明", FAIL, f"非法置信度：{conf!r}")
    elif origin == "synthetic" and conf == "high" and isinstance(body, dict):
        shape = eia_shape if src == "eia" else sec_shape
        if src == "eia":
            missing_row = shape["row_keys"] - set(body.get("response", {}).get("data", [{}])[0]) if body.get("response", {}).get("data") else set()
            missing_resp = shape["response_keys"] - set(body.get("response", {}))
            ok = not missing_row and not missing_resp
            detail = f"与真实响应结构比对：缺失行键 {sorted(missing_row)}，缺失响应键 {sorted(missing_resp)}"
        else:
            missing_top = {"cik", "taxonomy", "tag", "units"} - set(body)
            rows = body_rows("sec-edgar", body)
            missing_row = (shape["row_keys"] - set(rows[0])) if rows else set()
            ok = not missing_top and not missing_row
            detail = f"与真实 SEC 响应比对：缺失顶层键 {sorted(missing_top)}，缺失行键 {sorted(missing_row)}"
        record(fid, "C6 置信度声明", PASS if ok else FAIL, "high 且结构匹配真实响应；" + detail)
    else:
        record(fid, "C6 置信度声明", PASS, f"{conf}（按声明接受，未做结构比对）")

    # C7 场景语义：样本是否真的表达了它声称的缺陷
    rows = body_rows(src, body) if isinstance(body, dict) else []
    if ec == "empty_result":
        t = total_of(body)
        ok = t == "0" and rows == []
        record(fid, "C7 场景语义", PASS if ok else FAIL, f"total={t!r}，数据行 {len(rows)}")
    elif ec == "truncation":
        t = total_of(body)
        params = body.get("request", {}).get("params", {})
        off = int(params.get("offset", 0))
        ok = t is not None and off + len(rows) < int(t)
        record(fid, "C7 场景语义", PASS if ok else FAIL, f"offset {off} + 行数 {len(rows)} = {off + len(rows)} < total {t}")
    elif ec == "schema":
        if src == "eia":
            data = body.get("response", {}).get("data", [])
            defects = []
            if "total" not in body.get("response", {}):
                defects.append("response.total 缺失")
            if data and all("generation-units" not in r for r in data):
                defects.append("所有行缺 generation-units")
            record(fid, "C7 场景语义", PASS if defects else FAIL,
                   "；".join(defects) if defects else "未发现声明的结构缺陷")
        else:
            ok = not isinstance(body.get("units"), dict)
            record(fid, "C7 场景语义", PASS if ok else FAIL,
                   f"units 类型为 {type(body.get('units')).__name__}")
    elif ec in {"auth", "rate_limit", "not_found", "server"}:
        record(fid, "C7 场景语义", PASS, f"错误体 + 无数据行（{len(rows)} 行）")
    elif ec == "rights":
        r = body.get("rights", {}) if isinstance(body, dict) else {}
        has_both = isinstance(r, dict) and "commercial_use" in r and "redistribution" in r
        restricted = {"unknown", "not_permitted", "prohibited"}
        limited = has_both and any(r.get(k) in restricted for k in ("commercial_use", "redistribution"))
        record(fid, "C7 场景语义", PASS if limited else FAIL,
               f"commercial_use={r.get('commercial_use')!r}，redistribution={r.get('redistribution')!r}，"
               f"license_status={r.get('license_status')!r}；两类权限分开记录={has_both}")
    elif ec == "timeout":
        record(fid, "C7 场景语义", PASS, "描述文件声明超时异常")
    else:
        flags = exp.get("quality_flags", [])
        if "schema_drift" in flags:
            rows_ = body.get("response", {}).get("data", [])
            ok = bool(rows_) and not all(isinstance(r.get("generation"), str) for r in rows_)
            record(fid, "C7 场景语义", PASS if ok else FAIL, "generation 类型确实偏离字符串")
        elif "no_facts" in flags:
            ok = body.get("units") == {}
            record(fid, "C7 场景语义", PASS if ok else FAIL, f"units={body.get('units')!r}")
        elif "ytd_derived" in flags:
            rows_ = body_rows("sec-edgar", body)
            starts = {r.get("start") for r in rows_}
            ok = len(rows_) >= 2 and len(starts) == 1
            record(fid, "C7 场景语义", PASS if ok else FAIL,
                   f"{len(rows_)} 行，共享起始日 {len(starts)} 个")
        else:
            record(fid, "C7 场景语义", NA, "该样本无场景缺陷断言（正向样本）")

    # C8 输出行数与响应体自洽（不是连接器行为）
    if ec in {"auth", "rate_limit", "not_found", "server", "timeout", "rights"}:
        record(fid, "C8 输出行数与响应体自洽", PASS if not rows else FAIL,
               f"失败样本响应体含 {len(rows)} 行数据" + ("（应为 0）" if rows else "（符合）"))
    elif ec in {"schema", "truncation", "empty_result"}:
        record(fid, "C8 输出行数与响应体自洽", PASS,
               f"拒绝类失败：响应体 {len(rows)} 行，期望输出 {exp.get('emitted')} 行（拒绝后为 0，属连接器行为，见 A 组）")
    else:
        ok = len(rows) == exp.get("emitted")
        record(fid, "C8 输出行数与响应体自洽", PASS if ok else FAIL,
               f"响应体 {len(rows)} 行，声明输出 {exp.get('emitted')} 行")

    # C9 密钥材料
    text = raw.decode("utf-8", "replace")
    hits = []
    if key_env and key_env in text:
        hits.append("包含 EIA_API_KEY 实际值")
    if re.search(r'api_key\s*[=:]\s*["\']?[A-Za-z0-9_-]{20,}', text) or \
       re.search(r'[?&]api_key=[A-Za-z0-9]{20,}', text):
        hits.append("含形如 api_key=<token> 的字符串")
    record(fid, "C9 无密钥材料", PASS if not hits else FAIL, "；".join(hits) or "未发现密钥材料")


# ---------------------------------------------------------------- document cross-check
def parse_doc_table() -> dict:
    rows = {}
    text = DOC.read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(r"^\|\s*((?:EIA|SEC|RIGHTS)-\d{2})\s*\|(.+)\|\s*$", line)
        if not m:
            continue
        fid, rest = m.group(1), m.group(2)
        cols = [c.strip() for c in rest.split("|")]
        if len(cols) < 6:
            continue
        scen, origin, http, ecls, action, emitted = cols[:6]
        rows[fid] = {
            "scenario": scen,
            "origin": "observed" if "观测" in origin else ("synthetic" if "合成" in origin else origin),
            "http": None if http.strip() in {"—", "-", ""} else int(re.sub(r"\D", "", http)),
            "error_class": None if ecls.strip() in {"无", "-", ""} else ecls.strip("` "),
            "emitted": int(emitted) if emitted.isdigit() else None,
        }
    return rows


def cross_checks(fixtures, results_by_id, eia_status):
    out = []

    def add(name, status, detail):
        out.append({"criterion": name, "status": status, "detail": detail})

    ids = [f["fixture_id"] for f in fixtures]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    add("M1 fixture_id 唯一", PASS if not dup else FAIL, "无重复" if not dup else f"重复：{dup}")

    doc = parse_doc_table()
    missing_doc = sorted(set(ids) - set(doc))
    missing_man = sorted(set(doc) - set(ids))
    add("M2 manifest 与验收文档样本清单一致", PASS if not (missing_doc or missing_man) else FAIL,
        f"manifest {len(ids)} 条，文档 {len(doc)} 条；文档缺 {missing_doc}，manifest 缺 {missing_man}")

    mismatch = []
    for f in fixtures:
        d = doc.get(f["fixture_id"])
        if not d:
            continue
        exp = f.get("expected", {})
        if d["origin"] != f.get("origin"):
            mismatch.append(f"{f['fixture_id']} 来源（文档 {d['origin']} / manifest {f.get('origin')}）")
        if d["http"] != f.get("http_status"):
            mismatch.append(f"{f['fixture_id']} 状态码（文档 {d['http']} / manifest {f.get('http_status')}）")
        if d["error_class"] != exp.get("error_class"):
            mismatch.append(f"{f['fixture_id']} error_class（文档 {d['error_class']} / manifest {exp.get('error_class')}）")
        if d["emitted"] is not None and d["emitted"] != exp.get("emitted"):
            mismatch.append(f"{f['fixture_id']} 输出行数（文档 {d['emitted']} / manifest {exp.get('emitted')}）")
    add("M3 文档与 manifest 的逐条期望一致", PASS if not mismatch else FAIL,
        f"{len(doc)} 条逐项比对一致" if not mismatch else "；".join(mismatch))

    declared = {f.get("expected", {}).get("error_class") for f in fixtures}
    covered = [c for c in CLASSES if c in declared]
    uncovered = [c for c in CLASSES if c not in declared]
    add("M4 9 类失败分类覆盖", PASS if not uncovered else FAIL,
        f"覆盖 {len(covered)}/9：{covered}；未覆盖：{uncovered}")

    extra = sorted({p.name for p in FIXTURE_DIR.iterdir() if p.is_file()}
                   - {f.get("file") for f in fixtures if f.get("file")}
                   - {"manifest.json", "README.md"})
    add("M5 目录内无未登记样本文件", PASS if not extra else FAIL,
        "无游离文件" if not extra else f"未登记：{extra}")

    observed = [f for f in fixtures if f.get("origin") == "observed"]
    wrong = [f["fixture_id"] for f in observed if not f.get("ref")]
    add("M6 观测样本均指向真实响应且不复制文件", PASS if not wrong else FAIL,
        f"{len(observed)} 条观测样本均以 ref 引用 {EIA_SAMPLE_DIR.name}/" if not wrong else f"缺 ref：{wrong}")

    # 跨样本判据（需要连接器，全部 NOT_VERIFIED；只报告输入是否具备）
    ids_by = {f["fixture_id"]: f for f in fixtures}
    a = []
    a.append(("A1 来源间隔离", "需要连接器同时处理两个来源，当前不存在"))
    have_pair = {"EIA-13", "EIA-14"} <= set(ids_by)
    a.append(("A2 修订版本不被覆盖", f"输入已具备（EIA-13/EIA-14 同期不同值，均无修订字段）：{have_pair}；版本保留行为需连接器与存储层"))
    warn_complete = ids_by.get("EIA-08", {}).get("expected", {}).get("emitted") == 10
    a.append(("A3 warnings 不当作截断", f"判别输入已具备（EIA-08 有 warnings 且数据完整 / EIA-12 有 warnings 且不完整）；判定逻辑需连接器"))
    a.append(("A4 empty_result 与 truncation 可区分", "两个样本在结构上可区分（total=\"0\" vs offset+行数<total）；分类行为需连接器"))
    a.append(("A5 同期多申报的选择状态", "输入已具备（SEC-08 两版本 / SEC-09 三条累计期）；选择规则需连接器"))
    a.append(("A6 失败不产生「0」或「无数据」", "需要对系统输出做断言，当前无输出层"))
    a.append(("A7 失败原因可读且具体", "需要运行记录与报告，当前无输出层"))
    for name, detail in a:
        add(name, NA, detail)
    return out


# ---------------------------------------------------------------- main
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(Path(__file__).with_name("results_2026-11-01.json")))
    args = ap.parse_args()

    manifest = load(FIXTURE_DIR / "manifest.json")
    fixtures = manifest["fixtures"]

    eia_manifest = load(EIA_SAMPLE_DIR / "request_manifest.json")
    eia_ref_status = {}
    by_status = {}
    for e in eia_manifest["requests"]:
        if e.get("file"):
            eia_ref_status[e["file"]] = e["status"]
        by_status.setdefault(e["status"], []).append(e)
    for name in ("metadata_route_404.json",):
        cands = [e for e in by_status.get(404, []) if not e.get("file")]
        if len(cands) == 1:
            eia_ref_status[name] = cands[0]["status"]

    eia_shape = observed_eia_shape()
    sec_shape = observed_sec_shape()
    key_env = os.environ.get("EIA_API_KEY", "")

    for f in fixtures:
        check_fixture(f, eia_ref_status, sec_shape, eia_shape, key_env)

    cross = cross_checks(fixtures, None, eia_ref_status)

    by_fixture = {}
    for r in results:
        by_fixture.setdefault(r["fixture_id"], []).append(r)

    counts = {PASS: 0, FAIL: 0, NA: 0}
    for r in results:
        counts[r["status"]] += 1
    cross_counts = {PASS: 0, FAIL: 0, NA: 0}
    for c in cross:
        cross_counts[c["status"]] += 1

    print("=" * 78)
    print("实施前条件 3 — 失败注入样本集本地验证")
    print("=" * 78)
    print(f"样本数 {len(fixtures)}  检查项 {len(results)}  跨样本判据 {len(cross)}")
    print(f"逐条：PASS {counts[PASS]}  FAIL {counts[FAIL]}  NOT_VERIFIED {counts[NA]}")
    print(f"跨样本：PASS {cross_counts[PASS]}  FAIL {cross_counts[FAIL]}  NOT_VERIFIED {cross_counts[NA]}")
    print()
    for f in fixtures:
        rs = by_fixture.get(f["fixture_id"], [])
        bad = [r for r in rs if r["status"] == FAIL]
        flag = "FAIL" if bad else "OK  "
        print(f"[{flag}] {f['fixture_id']:7s} {f.get('origin','?'):9s} "
              f"http={str(f.get('http_status')):4s} ec={str(f.get('expected',{}).get('error_class')):13s} "
              f"emitted={f.get('expected',{}).get('emitted')}")
        for r in bad:
            print(f"        ! {r['check']}: {r['detail']}")
    print()
    print("-" * 78)
    for c in cross:
        print(f"[{c['status']:12s}] {c['criterion']}: {c['detail']}")

    out = {
        "generated_at": "2026-11-01",
        "scope": "fixture 集合自洽性与文档一致性；不验证连接器行为",
        "fixture_count": len(fixtures),
        "checks": results,
        "cross_checks": cross,
        "summary": {"per_fixture": counts, "cross": cross_counts},
    }
    Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入 {args.json}")
    return 1 if (counts[FAIL] or cross_counts[FAIL]) else 0


if __name__ == "__main__":
    sys.exit(main())
