"""인바운드 타겟 국가 브리핑 리포트를 생성하는 CLI."""
import argparse
import pathlib
import re
import sys

import yaml

# build_axes가 datalab-fetch Skill의 client/normalize 모듈을 import하므로,
# build_axes를 import하기 전에 두 Skill의 scripts 디렉터리를 모두
# sys.path에 올려야 한다.
# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FETCH_SCRIPTS = _SKILLS_ROOT / "datalab-fetch" / "scripts"
_BRIEF_SCRIPTS = _SKILLS_ROOT / "inbound-country-brief" / "scripts"
for _path in (_FETCH_SCRIPTS, _BRIEF_SCRIPTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import client
import period
from build_axes import PROFILES_PATH, build_axis_values
import purpose
import rivalry
from report import render_report
from score import score_both
import workspace  # noqa: E402

CACHE_DIR = workspace.cache_dir()
SESSION_FILE = workspace.session_file()
YM = re.compile(r"^\d{6}$")


def resolve_profile(value, profiles_data):
    """사용자가 쓴 말을 프로필 이름으로 바꾼다. 모르면 None.

    "호텔"이라고 쓴 사람에게 영어 키 다섯 개를 늘어놓는 대신 알아듣는다.
    별칭은 profiles.yaml 이 선언한다 — 프로필을 늘리는 사람이 별칭도
    같은 자리에서 늘리게 하려고 코드에 박아 두지 않았다.
    """
    text = str(value or "").strip()
    if text in profiles_data:
        return text
    lowered = text.lower()
    for name, entry in profiles_data.items():
        if name.lower() == lowered:
            return name
        for alias in entry.get("aliases") or ():
            if str(alias).strip().lower() == lowered:
                return name
    return None


def available_profiles(value, profiles_data):
    lines = [f"알 수 없는 프로필: {value}", "사용할 수 있는 프로필:"]
    for name in sorted(profiles_data):
        entry = profiles_data[name]
        aliases = ", ".join(entry.get("aliases") or ())
        tail = f" — {aliases}" if aliases else ""
        lines.append(f"  {name}  {entry['label']}{tail}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="방한 인바운드 타겟 국가 브리핑")
    # 이름을 손으로 적어 두면 프로필이 늘어도 도움말은 그대로 남는다.
    # 틀리게 넣어야 목록이 나오는데, 그때는 이미 --period까지 맞춰
    # 적은 뒤라 사용자는 두 번 일한다.
    _names = sorted(yaml.safe_load(PROFILES_PATH.read_text(encoding="utf-8")))
    parser.add_argument("--profile", required=True,
                        help="업종 프로필: " + " / ".join(_names)
                             + " (면세점·호텔처럼 풀어 써도 됩니다)")
    period.add_arguments(parser)
    parser.add_argument("--out", required=True, help="출력 HTML 경로")
    parser.add_argument("--top", type=int, default=10, help="표시할 상위 국가 수")
    args = parser.parse_args(argv)

    try:
        args.ym1, args.ym2 = period.from_args(args)
    except period.PeriodError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.top < 1:
        print(f"--top 값이 잘못되었습니다: {args.top} (1 이상의 정수여야 합니다)",
              file=sys.stderr)
        return 2

    # profiles.yaml을 한 번만 읽어서 가중치와 라벨이 서로 다른 읽기에서
    # 불일치하는 일이 없도록 한다
    profiles_data = yaml.safe_load(PROFILES_PATH.read_text())
    chosen = resolve_profile(args.profile, profiles_data)
    if chosen is None:
        print(available_profiles(args.profile, profiles_data), file=sys.stderr)
        return 2

    weights = dict(profiles_data[chosen]["weights"])
    label = profiles_data[chosen]["label"]

    try:
        axis_values, meta = build_axis_values(
            args.ym1, args.ym2, cache_dir=CACHE_DIR, session_file=SESSION_FILE)
    except client.SessionExpired:
        print("로그인 세션이 만료되었습니다. 다음 명령으로 세션을 갱신한 뒤 "
              "다시 시도하세요:\n"
              f"  python3 "
              f"{workspace.display_path(_SKILLS_ROOT, 'datalab-auth', 'login.py')}",
              file=sys.stderr)
        return 3
    except client.FetchError:
        print("데이터를 가져오지 못했습니다. 네트워크/프록시 상태를 확인하고, "
              "다음 명령으로 세션 상태를 진단해보세요:\n"
              f"  python3 "
              f"{workspace.display_path(_SKILLS_ROOT, 'datalab-auth', 'check_session.py')}",
              file=sys.stderr)
        return 4

    df = score_both(axis_values, weights)
    if df.empty or df["총점_보정"].notna().sum() == 0:
        # 기간이 원인이면 그렇게 말한다. 규모 축(방한객수)이 비면 어떤
        # 국가도 점수를 받지 못하므로 그 지표 하나로 판단할 수 있다.
        gap = period.explain_gap("NAT_08_01_021", args.ym1, args.ym2)
        if gap:
            print(gap, file=sys.stderr)
            return 4
        print("평가 가능한 국가가 없습니다. 요청한 기간에 대해 점수를 산출할 "
              "수 있는 데이터가 반환되지 않았습니다. 기간을 조정하거나 "
              "다음 명령으로 세션 상태를 진단해보세요:\n"
              f"  python3 "
              f"{workspace.display_path(_SKILLS_ROOT, 'datalab-auth', 'check_session.py')}",
              file=sys.stderr)
        return 4

    # 입국목적은 점수에 넣지 않는다. 상위 국가에 대해서만 맥락으로 붙인다.
    ranked_names = [str(n) for n in
                    df[df["총점_보정"].notna()]["국가"].head(args.top)]
    purpose_mix, purpose_missing = purpose.for_countries(
        ranked_names, args.ym1, args.ym2, cache_dir=CACHE_DIR,
        session_file=SESSION_FILE)
    # "그 나라에서 한국이 몇 번째인가"도 점수에 넣지 않는다. 상위
    # 셋만 부른다 — 나라마다 호출 하나이고 표가 여덟 해를 준다.
    rivalry_tables, rivalry_missing = rivalry.for_countries(
        ranked_names[:3], cache_dir=CACHE_DIR, session_file=SESSION_FILE)

    html = render_report(df, meta, profile_label=label, top_n=args.top,
                         weights=weights, purpose_mix=purpose_mix,
                         purpose_missing=purpose_missing,
                         rivalry_tables=rivalry_tables,
                         rivalry_missing=rivalry_missing)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"리포트를 생성했습니다: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
