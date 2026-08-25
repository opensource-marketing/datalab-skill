"""여러 지역을 같은 잣대로 나란히 놓는 리포트를 만드는 CLI."""
import argparse
import html as html_mod
import pathlib
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "datalab-fetch" / "scripts",
           _SKILLS_ROOT / "inbound-country-brief" / "scripts",
           _SKILLS_ROOT / "region-market-scan" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import client
import codes
import market_compare as compare
import normalize
import period
from market_render import ESTIMATE_NOTE, STOCK_NOTE, _esc, _fmt
from report import STYLE, footer_text, table_head
import workspace  # noqa: E402

CACHE_DIR = workspace.cache_dir()
SESSION_FILE = workspace.session_file()
MAX_MONTHS = 18
MAX_REGIONS = 8
LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")

JUDGEMENT_NOTE = (
    "이 표는 <b>어느 값이 좋다고 말하지 않습니다</b>. 객실당 수요가 높으면 "
    "공급이 빠듯하다는 뜻인데, 그것이 기회인지 위험인지는 사업 모델이 "
    "정합니다. 아래 용어 설명은 값이 크다는 것이 무엇을 뜻하는지만 적습니다."
)


def _resolve(queries):
    """지역 문자열들을 (코드, 이름) 목록으로 바꾼다. 실패하면 None."""
    targets = []
    for query in queries:
        if codes.is_sido(query):
            print(f"시도 코드({query})는 지원하지 않습니다. 시군구 5자리 "
                  f"코드나 시군구 이름을 넣으세요.", file=sys.stderr)
            return None
        hits = codes.resolve_region(query)
        if not hits:
            print(f"일치하는 지역이 없습니다: {query}", file=sys.stderr)
            hint = codes.sido_hint(query)
            if hint:
                print(hint, file=sys.stderr)
            return None
        if len(hits) > 1:
            print(f"'{query}'에 여러 지역이 일치합니다. 하나를 골라 다시 "
                  f"실행하세요:", file=sys.stderr)
            for code, name in hits:
                print(f"  {code}  {name}", file=sys.stderr)
            hint = codes.sido_hint(query)
            if hint:
                print(hint, file=sys.stderr)
            return None
        note = codes.merged_city_note(hits[0][0])
        if note:
            print(note, file=sys.stderr)
        if hits[0] in targets:
            print(f"같은 지역이 두 번 들어왔습니다: {query}", file=sys.stderr)
            return None
        targets.append(hits[0])
    return targets


def _table_html(frame):
    head = table_head(frame.columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_fmt(v)}</td>" for v in row) + "</tr>"
        for row in frame.itertuples(index=False, name=None))
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def _glossary_html():
    rows = "".join(
        f"<tr><td>{_esc(name)}</td><td>{html_mod.escape(meaning)}</td></tr>"
        for name, meaning in compare.COLUMN_MEANING.items())
    return (f"<h2>값이 크다는 것의 뜻</h2>"
            f'<div class="warn">{JUDGEMENT_NOTE}</div>'
            f'<div class="scroll"><table><thead><tr><th scope="col">지표</th>'
            f"<th scope='col'>값이 크면</th></tr></thead><tbody>{rows}</tbody></table></div>")


def _notes_html(meta):
    """기간을 줄여 부른 사실과 통합시 안내. 비교표에서는 특히 중요하다 —
    지역마다 다른 창으로 잰 값을 나란히 놓으면 순위 자체가 거짓이 된다."""
    blocks = []
    lines = period.summarize_notes(meta.get("기간조정") or {})
    if lines:
        items = "".join(f"<li>{_esc(line)}</li>" for line in lines)
        blocks.append('<div class="warn">지표마다 데이터가 나오는 시점이 '
                      f"다릅니다.<ul>{items}</ul></div>")
    for note in meta.get("통합시안내") or ():
        blocks.append(f'<div class="warn">{_esc(note)}</div>')
    return "".join(blocks)


def _missing_html(meta):
    if not meta["미수록"]:
        return ""
    rows = "".join(
        f"<tr><td>{_esc(region)}</td><td>{_esc(qid)}</td>"
        f"<td>{_esc(normalize.reason_text(reason))}</td></tr>"
        for region, reasons in sorted(meta["미수록"].items())
        for qid, reason in sorted(reasons.items()))
    return (f"<h2>가져오지 못한 지표</h2>"
            f'<p class="note">비어 있는 칸은 값이 0이 아니라 데이터가 '
            f"없다는 뜻입니다.</p>"
            f'<div class="scroll"><table><thead><tr><th scope="col">지역</th><th scope="col">지표</th>'
            f"<th scope='col'>사유</th></tr></thead><tbody>{rows}</tbody></table></div>")


def render(frame, meta, sort_column, sort_note):
    warn = ""
    if meta["세션상태"] == "만료":
        warn = ('<div class="warn">로그인 세션이 만료되어 일부 지표를 '
                f"가져오지 못했습니다. <code>{_esc(LOGIN_HINT)}</code>를 "
                "실행한 뒤 다시 생성하세요. (datalab-auth 스킬)</div>")
    note = f'<p class="note">{_esc(sort_note)}</p>' if sort_note else ""
    names = " · ".join(_esc(n) for n in frame["지역"]) if not frame.empty else ""
    return (
        f"{STYLE}"
        f'<div class="wrap">'
        f"<h1>지역 관광시장 비교</h1>"
        f'<p class="sub">{names}<br>기준기간 {_esc(meta["기준기간"])} · '
        f'재고 기준 {_esc(meta["재고기준월"])}</p>'
        f"{warn}"
        f'<div class="warn">{ESTIMATE_NOTE}</div>'
        f'<div class="warn">{STOCK_NOTE}</div>'
        f"<h2>비교표</h2>"
        f'<p class="note">{_esc(sort_column)} 기준 내림차순입니다.</p>'
        f"{note}"
        f"{_table_html(frame)}"
        f"{_glossary_html()}"
        f"{_notes_html(meta)}"
        f"{_missing_html(meta)}"
        f'<p class="note">한 지역을 깊게 보려면 같은 스킬의 '
        f"<code>scan.py</code>를 쓰세요.</p>"
        f"<footer>{_esc(footer_text())}</footer>"
        f"</div>"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="여러 지역의 관광시장을 같은 잣대로 비교한다")
    parser.add_argument("--region", action="append", required=True,
                        help="시군구 이름 또는 코드. 두 곳 이상 넣는다")
    period.add_arguments(parser)
    parser.add_argument("--out", required=True, metavar="FILE")
    parser.add_argument("--sort", default=compare.DEFAULT_SORT,
                        choices=compare.SORTABLE)
    parser.add_argument("--asc", action="store_true", help="오름차순으로 정렬")
    args = parser.parse_args(argv)

    if len(args.region) < 2:
        print("--region 을 두 개 이상 넣으세요. 한 곳만 보려면 scan.py를 "
              "쓰세요.", file=sys.stderr)
        return 1
    if len(args.region) > MAX_REGIONS:
        print(f"지역이 {len(args.region)}곳입니다. {MAX_REGIONS}곳 이내로 "
              f"줄이세요.", file=sys.stderr)
        return 1
    try:
        args.ym1, args.ym2 = period.from_args(args, max_months=MAX_MONTHS)
    except period.PeriodError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    targets = _resolve(args.region)
    if targets is None:
        return 2

    try:
        frame, meta = compare.build(targets, args.ym1, args.ym2,
                                    cache_dir=str(CACHE_DIR),
                                    session_file=str(SESSION_FILE))
    except client.SessionExpired:
        print(f"세션이 만료됐습니다. 다음을 실행하세요:\n  {LOGIN_HINT}",
              file=sys.stderr)
        return 3

    if frame.empty:
        if meta["세션상태"] == "만료":
            print(f"세션이 만료되어 지표를 하나도 가져오지 못했습니다.\n"
                  f"  {LOGIN_HINT}", file=sys.stderr)
            return 3
        print("지표를 하나도 가져오지 못했습니다. 지역과 기간을 확인하세요.",
              file=sys.stderr)
        return 4

    frame, sort_note = compare.sort_table(frame, args.sort,
                                          descending=not args.asc)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(frame, meta, args.sort, sort_note), encoding="utf-8")
    print(f"비교 리포트를 생성했습니다: {out} "
          f"(비교 {meta['비교지역수']}/{meta['요청지역수']}곳)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
