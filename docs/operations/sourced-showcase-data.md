# Sourced showcase data

Date: 2026-09-21

## Purpose

This dataset provides a larger presentation library for expert experience and Watcher workflows without pretending to contain real interviews or real incident records.

All content is:

- adapted from public guidance;
- rewritten in neutral third-person language;
- labelled `【公开资料改编｜非真实个人访谈】`;
- seeded through formal HTTP APIs;
- traceable to the public source title and URL.

## Public sources

| Key | Source | Publisher |
| --- | --- | --- |
| `gb42101` | [GB/T 42101-2022 旅游景区安全与客流疏导要求](https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3432/site/attach/0/4b020844005848a69939a5001acb6113.pdf) | 国家标准 |
| `safe-city` | [国家安全发展示范城市建设指导手册](https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202012/t20201207_374342.shtml) | 国务院安委会办公室 |
| `holiday-safety` | [应急管理部假期安全提示](https://www.sz.gov.cn/cn/xxgk/zfxxgj/yjgl/yjgg_81606/content/post_12421696.html) | 应急管理部 |
| `large-crowd` | [旅游景区超大客流安全风险防范与应对方案](http://cqjlp.gov.cn/bmjz/qzfbm_97119/qwhlyw_97727/zwgk_97124/gkml/jczwgk/lyly/ggfw/lyaqyjczxx/202505/t20250516_14628624.html) | 重庆市九龙坡区人民政府 |
| `weather-guide` | [焉耆县旅游安全极端天气应急处置信息指南](https://www.xjyq.gov.cn/xjyqx/c118406/202507/3141420829c643bf9308011b4e5c70e0.shtml) | 焉耆县人民政府 |
| `ropeway-rule` | [客运索道安全监督管理规定](https://scjgj.cq.gov.cn/zfxxgk_225/fdzdgknr/lzyj/gz/gjbwgz/202012/W020211103719087450111.pdf) | 国家市场监督管理总局 |
| `food-law` | [中华人民共和国食品安全法（2021修正）](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=90359) | 全国人民代表大会常务委员会 |
| `lost-person` | [旅游景区游客走失联动处置公开案例](https://gaj.wuhan.gov.cn/hjfc/jdxw/202608/t20260826_2838773.html) | 公安机关公开信息 |

## Seed volume

| Item | Target |
| --- | ---: |
| Real expert accounts | 4 |
| Source knowledge records | 24 |
| Source events | 24 |
| Linked tasks | 24 |
| Interviews | 24 |
| Experience cards | 18 |
| Watcher policies | 15 |
| Watcher runs | 15+ |

The four expert profiles are bound to existing users: `knowledge-owner`, `wangfang`, `chenyu`, and `liming`. No fake employee identities are created.

## Run

```powershell
$env:MEMORY_PALACE_UAT_BASE_URL = 'http://127.0.0.1:8090'
$env:ADMIN_USERNAME = 'admin'
$env:ADMIN_PASSWORD = '<from deployment secret>'

uv run --no-project --with-requirements requirements.txt `
  python -m scripts.unified_agent_uat.cli `
  showcase-seed --sections sourced
```

The seeder is idempotent by source event, interview title, source knowledge ID, task session ID, and Watcher policy `sourced_key`.
