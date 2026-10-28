# Test results

| phase | suite | exit | passed | failed | log |
| --- | --- | ---: | ---: | ---: | --- |
| before | target | 1 | 0 | 4 | `records/before_target.log` |
| before | regression | 0 | 4 | 0 | `records/before_regression.log` |
| after | target | 0 | 4 | 0 | `records/after_target.log` |
| after | regression | 0 | 4 | 0 | `records/after_regression.log` |

The same files and the same assertions are used in both phases. The only difference is the code under `demo_project/issuehub/`.
