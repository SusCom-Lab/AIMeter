# 使用方法

```python

import ecmhongz.monitor as Monitor

#开始监控(task name随便取，用于给自己区分)
Monitor.start(task_name = "easy_test", sampling_interval = 0.2, output_format = "csv")

# 代码

# 结東监控
Monitor.stop()

画图代码
Monitor.draw(table_path = '/home/ldaphome/hhz/workspace/easy_test_20250331_161129.csy',format ="csv")
```

