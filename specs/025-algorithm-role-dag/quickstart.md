# Quickstart: Built-in Algorithm Role DAG

Enable the five specialist stages for a conversational mission:

```bash
lunar-agent solve "根据订单数据设计配送路线" \
  --runtime mock --role-dag --json --home .lunar
```

Use `status <run-id> --json` to inspect the physical tasks and their verified dependency
artifacts. Omitting `--role-dag` keeps the compatible four-stage Feature 024 plan.
