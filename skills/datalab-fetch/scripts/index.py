"""qid 색인 검색 — "그런 지표가 있나?"에 답하는 계층.

색인(catalog/qid_index.yaml)은 데이터랩 화면 656개 qid를 담고 있지만
**검증되지 않았다.** 컬럼 의미도, 인증 등급도, 실제로 값이 나오는지도
확인하지 않은 상태다. 반면 카탈로그 두 개(qid_catalog.yaml,
loc_qid_catalog.yaml)의 항목은 실제 호출로 확인하고 컬럼까지 적어 둔
것이다.

검색 결과는 이 둘을 반드시 구분해서 보여 준다. 구분이 사라지면
"이름이 그럴듯하니 맞겠지"로 지표를 잘못 쓰게 되고, 그건 이 프로젝트가
이미 한 번 저지른 실수다(NAT_08_01_007을 방문목적으로 오해한 건).
"""
import argparse
import json
import pathlib
import re
import sys

import yaml

CATALOG_DIR = pathlib.Path(__file__).resolve().parents[1] / "catalog"
INDEX_PATH = CATALOG_DIR / "qid_index.yaml"
CURATED_PATHS = {
    "인바운드": CATALOG_DIR / "qid_catalog.yaml",
    "지역": CATALOG_DIR / "loc_qid_catalog.yaml",
    "공급": CATALOG_DIR / "bzm_qid_catalog.yaml",
    "테마": CATALOG_DIR / "theme_qid_catalog.yaml",
    "관광지": CATALOG_DIR / "poi_qid_catalog.yaml",
    "아웃바운드": CATALOG_DIR / "outbound_qid_catalog.yaml",
    "축제": CATALOG_DIR / "fes_qid_catalog.yaml",
    "전국": CATALOG_DIR / "main_qid_catalog.yaml",
    "빅데이터": CATALOG_DIR / "bda_qid_catalog.yaml",
    "인구감소": CATALOG_DIR / "popl_qid_catalog.yaml",
    "세계": CATALOG_DIR / "world_qid_catalog.yaml",
    "관광수요": CATALOG_DIR / "activate_qid_catalog.yaml",
    "캠핑": CATALOG_DIR / "camp_qid_catalog.yaml",
    "크루즈": CATALOG_DIR / "crus_qid_catalog.yaml",
    "불편신고": CATALOG_DIR / "cpln_qid_catalog.yaml",
    "성연령": CATALOG_DIR / "sexage_qid_catalog.yaml",
    "출입국": CATALOG_DIR / "entry_qid_catalog.yaml",
    "집중분석": CATALOG_DIR / "focus_qid_catalog.yaml",
    "실태조사": CATALOG_DIR / "survey_qid_catalog.yaml",
    "관광안내": CATALOG_DIR / "cnsel_qid_catalog.yaml",
    "소셜미디어": CATALOG_DIR / "social_qid_catalog.yaml",
    "국가별연간": CATALOG_DIR / "yearrep_qid_catalog.yaml",
}

_index_cache = None
_curated_cache = None

# 조회 축: 이 파라미터가 있으면 그 축으로 조회하는 지표다.
# 위에서부터 먼저 맞는 것을 쓴다 — CONT_ID와 SGG_CD를 함께 받는 지표는
# 관광지 지표이고 SGG_CD는 그 관광지가 속한 지역을 좁히는 보조값이다.
_AXIS_RULES = [
    ("관광지", ("CONT_ID",)),
    ("국가", ("natCd", "NAT_CD", "natNm")),
    ("지역", ("SGG_CD", "SIDO_CD", "SGG_NM")),
    ("축제", ("FSTV_ID", "FSTVL_ID", "FEST_ID")),
]




def load_index(path=None):
    """qid 색인을 읽는다. 인자가 없으면 결과를 캐시한다."""
    global _index_cache
    if path is not None:
        return yaml.safe_load(pathlib.Path(path).read_text())
    if _index_cache is None:
        _index_cache = yaml.safe_load(INDEX_PATH.read_text())
    return _index_cache


def curated_entries():
    """검증된 카탈로그의 qid → (카탈로그 이름, 항목)."""
    global _curated_cache
    if _curated_cache is None:
        found = {}
        for label, path in CURATED_PATHS.items():
            if not path.exists():
                continue
            for qid, entry in (yaml.safe_load(path.read_text()) or {}).items():
                found[qid] = (label, entry)
        _curated_cache = found
    return _curated_cache


def curated_qids():
    """검증된 카탈로그에 이미 들어 있는 qid → 카탈로그 이름."""
    return {qid: label for qid, (label, _) in curated_entries().items()}


def _caution(qid):
    """검증된 지표가 적어 둔 함정. 없으면 None.

    **`show` 가 이것을 찍지 않으면 안내가 거짓말이 된다.** 가이드
    스킬이 "표를 옮기기 전에 caution 을 읽어라"라며 이 명령을
    가리키는데, 정작 출력에 함정이 없으면 읽을 길이 없다.
    """
    hit = curated_entries().get(qid)
    return (hit[1].get("caution") if hit else None) or None


def _names(qid, entry):
    """이름을 모은다. 카탈로그 이름이 앞에 온다.

    색인의 이름은 사이트 JS의 dnname이라 비어 있을 수 있고, 화면마다
    다르게 붙어 있기도 하다. 검증하면서 우리가 확정한 이름이 있으면
    그것을 먼저 보여 준다.
    """
    names = list(entry.get("names") or [])
    curated = curated_entries().get(qid)
    if curated is not None:
        name = curated[1].get("name")
        if name and name not in names:
            names.insert(0, name)
    return names


def _axis_and_params(qid, entry):
    """조회축과 파라미터를 정한다.

    검증된 카탈로그가 있으면 그쪽을 쓴다. 색인의 파라미터는 화면 코드에서
    긁어온 힌트라 비어 있을 수 있는데(스윕이 못 읽은 화면), 그때 색인을
    믿으면 축이 "전국·기타"로 잘못 나온다.
    """
    curated = curated_entries().get(qid)
    if curated is not None:
        _, catalog_entry = curated
        # 축은 호출자가 고르는 파라미터(params)로만 정한다. fixed_params는
        # 우리가 늘 같은 값으로 보내는 상수이므로 축이 아니다 — 의료관광은
        # NAT_CD를 fixed_params로 보내지만 국가별 값이 나오지 않는다.
        params = sorted(catalog_entry.get("params") or ())
        declared = catalog_entry.get("query_axis")
        shown = sorted(set(params) | set(catalog_entry.get("fixed_params") or {}))
        return (declared or axis_of(params)), shown
    params = sorted(entry.get("params") or ())
    return axis_of(params), params


def axis_of(params):
    """파라미터 목록으로 조회 축을 추정한다.

    추정이다 — 색인의 파라미터 자체가 화면 코드에서 긁어온 힌트이기
    때문이다. 실제로 무엇을 넘겨야 하는지는 probe로 확인해야 한다.
    """
    have = set(params or ())
    for label, keys in _AXIS_RULES:
        if have & set(keys):
            return label
    return "전국·기타"


def _tokens(text):
    return [t for t in re.split(r"[\s,/·]+", text.strip()) if t]


def search(query, *, index=None, limit=20, include_commented=False):
    """이름·qid·화면 이름에서 질의어를 찾는다.

    질의어를 공백으로 나눠 모든 조각이 걸리는 항목만 남긴다. 조각이
    이름에 걸리면 화면 이름에 걸릴 때보다 높은 점수를 준다 — 지표
    이름이 화면 경로보다 사용자의 질문에 가깝기 때문이다.
    """
    entries = index if index is not None else load_index()
    curated = curated_qids()
    needles = [t.lower() for t in _tokens(query)]
    if not needles:
        return []

    hits = []
    for qid, entry in entries.items():
        if entry.get("commented") and not include_commented:
            continue
        names = _names(qid, entry)
        name_blob = " ".join(names).lower()
        other_blob = (qid + " " + " ".join(entry.get("screens") or [])).lower()

        score = 0
        for needle in needles:
            if needle in name_blob:
                score += 3
            elif needle in other_blob:
                score += 1
            else:
                score = -1
                break
        if score <= 0:
            continue
        axis, params = _axis_and_params(qid, entry)
        hits.append({
            "qid": qid,
            "names": names,
            "params": params,
            "screens": entry.get("screens") or [],
            "axis": axis,
            "commented": bool(entry.get("commented")),
            "catalog": curated.get(qid),
            "caution": _caution(qid),
            "score": score,
        })

    hits.sort(key=lambda h: (-h["score"], h["catalog"] is None, h["qid"]))
    return hits[:limit]


def describe(qid, index=None):
    """qid 하나의 색인 내용을 돌려준다. 없으면 None."""
    entries = index if index is not None else load_index()
    entry = entries.get(qid)
    if entry is None:
        return None
    axis, params = _axis_and_params(qid, entry)
    return {
        "qid": qid,
        "names": _names(qid, entry),
        "params": params,
        "screens": entry.get("screens") or [],
        "axis": axis,
        "commented": bool(entry.get("commented")),
        "catalog": curated_qids().get(qid),
        "caution": _caution(qid),
    }


def screens(index=None):
    """색인에 등장하는 화면별 qid 개수."""
    entries = index if index is not None else load_index()
    counts = {}
    for entry in entries.values():
        for screen in entry.get("screens") or []:
            counts[screen] = counts.get(screen, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def catalog_overview():
    """검증된 지표 전체를 카탈로그·섹션별로 정리해 줄 목록으로 돌려준다.

    무엇을 물어볼 수 있는지 한눈에 보여 주는 용도다. 미검증 색인은 넣지
    않는다 — 여기 있는 것은 실호출로 확인하고 컬럼 의미까지 적어 둔 것뿐이다.
    """
    grouped = {}
    for qid, (label, entry) in curated_entries().items():
        section = entry.get("section") or "기타"
        grouped.setdefault(label, {}).setdefault(section, []).append((qid, entry))

    total = sum(len(items) for sections in grouped.values()
                for items in sections.values())
    lines = [f"검증된 지표 {total}개"]
    for label in sorted(grouped):
        count = sum(len(v) for v in grouped[label].values())
        lines.append(f"\n## {label} ({count}개)")
        for section in sorted(grouped[label]):
            lines.append(f"\n### {section}")
            for qid, entry in sorted(grouped[label][section]):
                axis = entry.get("query_axis") or axis_of(entry.get("params"))
                lines.append(f"- `{qid}` {entry['name']} — 축 {axis}")
                caution = entry.get("caution")
                if caution:
                    lines.append(f"  - 주의: {caution}")
    return lines


def _render(hits):
    if not hits:
        print("찾은 지표가 없습니다. 다른 낱말로 검색해 보세요.")
        return
    for hit in hits:
        if hit["catalog"]:
            mark = f"[검증됨:{hit['catalog']}]"
        elif hit["commented"]:
            mark = "[미검증·주석]"
        else:
            mark = "[미검증]"
        print(f"\n{hit['qid']}  {mark}")
        print(f"  이름    : {' / '.join(hit['names']) or '-'}")
        print(f"  조회축  : {hit['axis']}")
        print(f"  파라미터: {', '.join(hit['params']) or '-'}")
        print(f"  화면    : {', '.join(hit['screens'])}")
        if hit.get("caution"):
            print(f"  주의    : {hit['caution']}")
    unverified = sum(1 for h in hits if not h["catalog"])
    if unverified:
        # 실 호출로 확인하는 도구는 카탈로그를 만들 때 쓰는 개발
        # 전용이라 배포본에는 없다(무엇인지는 개발자-검사도구.md).
        # 없는 파일을 부르라고 안내하는 대신, 배포본 사용자가 실제로
        # 할 수 있는 것 — 이름과 컬럼의 뜻을 단정하지 않는 것 — 을 적는다.
        print(f"\n미검증 {unverified}건. 이름·컬럼의 뜻을 단정하지 마세요.")
        print("  실제 호출로 확인하는 도구는 소스 저장소에만 있습니다.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="데이터랩 qid 색인 검색")
    sub = parser.add_subparsers(dest="mode", required=True)

    search_cmd = sub.add_parser("search", help="낱말로 지표를 찾는다")
    search_cmd.add_argument("query", nargs="+")
    search_cmd.add_argument("--limit", type=int, default=20)
    search_cmd.add_argument("--all", action="store_true",
                            help="화면 JS에서 주석 처리된 qid도 포함한다")
    search_cmd.add_argument("--json", action="store_true")

    show_cmd = sub.add_parser("show", help="qid 하나를 자세히 본다")
    show_cmd.add_argument("qid")
    show_cmd.add_argument("--json", action="store_true")

    sub.add_parser("screens", help="화면별 qid 개수")
    sub.add_parser("catalog", help="검증된 지표를 카탈로그·섹션별로 모두 보여준다")

    args = parser.parse_args(argv)

    if args.mode == "search":
        hits = search(" ".join(args.query), limit=args.limit,
                      include_commented=args.all)
        if args.json:
            print(json.dumps(hits, ensure_ascii=False, indent=2))
        else:
            _render(hits)
        return 0

    if args.mode == "show":
        found = describe(args.qid)
        if found is None:
            print(f"색인에 없는 qid입니다: {args.qid}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(found, ensure_ascii=False, indent=2))
        else:
            _render([{**found, "score": 0}])
        return 0

    if args.mode == "screens":
        for screen, count in screens().items():
            print(f"{count:5d}  {screen}")
        return 0

    for line in catalog_overview():
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
