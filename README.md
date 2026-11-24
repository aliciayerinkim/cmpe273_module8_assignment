# CMPE 273 Module 8: Primary-Secondary Replication

This project has two copies (replicas) of a product's stock count. The primary takes all the writes and copies them to the secondary in the background. I tested what happens when the secondary does not get the new value right away.

## How to run

Set up the venv once from the repo root (Git Bash on Windows):

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

Terminal 1, the secondary:

```bash
source .venv/Scripts/activate
python replica.py --role secondary --port 8002
```

Terminal 2, the primary:

```bash
source .venv/Scripts/activate
python replica.py --role primary --port 8001 --secondary-url http://127.0.0.1:8002
```

Terminal 3, the client commands:

```bash
source .venv/Scripts/activate
python client.py read primary
python client.py read secondary
python client.py read both
python client.py write 9
python client.py pause
python client.py resume
python client.py status
```

The client uses `PRIMARY_URL` and `SECONDARY_URL` if they are set. Otherwise it uses `http://127.0.0.1:8001` and `http://127.0.0.1:8002`.

## Architecture

<img width="1520" height="720" alt="architecture (2)" src="https://github.com/user-attachments/assets/1ee95b81-b7d3-4297-87d0-6a04cc705d85" />


## How it works

- Only the primary takes writes (`PUT /stock`). The secondary returns 403 if it gets a write request.
- When the primary gets a new value, it saves it and adds the update to a queue.
- A background thread sends the updates in the queue to the secondary (`POST /replicate`).
- The secondary only uses an update if its version is newer. Old or duplicate versions are ignored.
- I added pause and resume commands so I could stop replication and test a stale read.
- `GET /admin/status` shows if replication is paused and how many updates are waiting.

All the output below is real output from running the project. Each scenario shows the client output first, then the matching log lines from the primary and secondary terminals.

## Evidence: successful replication (Scenario 1)

Both replicas start at stock 10. I write 8, wait about 1 second, and read both again.

Client:

```
$ python client.py read both
primary:   stock=10 version=1
secondary: stock=10 version=1
Result: SAME
$ python client.py write 8
write ok: {'replica': 'primary', 'stock': 8, 'version': 2}
$ python client.py read both
primary:   stock=8 version=2
secondary: stock=8 version=2
Result: SAME
```

Primary log:

```
02:43:27 [primary] GET /stock -> 200 | stock=10 version=1
02:43:27 [primary] write saved, queued for replication (queue=1) | stock=8 version=2
02:43:27 [primary] PUT /stock -> 200 | stock=8 version=2
02:43:27 [primary] replicated version 2 to secondary (queue=0) | stock=8 version=2
02:43:28 [primary] GET /stock -> 200 | stock=8 version=2
```

Secondary log:

```
02:43:27 [secondary] GET /stock -> 200 | stock=10 version=1
02:43:27 [secondary] replication applied | stock=8 version=2
02:43:27 [secondary] POST /replicate -> 200 | stock=8 version=2
02:43:28 [secondary] GET /stock -> 200 | stock=8 version=2
```

### Going back to 10 before Scenario 2

Scenario 2 needs both replicas at 10. The simpler way was to just write 10 again, so I did not have to restart anything. This is a normal write, so the version goes up to 3. The stock is 10 on both again, which is what matters for the test.

```
$ python client.py write 10
write ok: {'replica': 'primary', 'stock': 10, 'version': 3}
$ python client.py read both
primary:   stock=10 version=3
secondary: stock=10 version=3
Result: SAME
```

Primary log:

```
02:43:35 [primary] write saved, queued for replication (queue=1) | stock=10 version=3
02:43:35 [primary] PUT /stock -> 200 | stock=10 version=3
02:43:35 [primary] replicated version 3 to secondary (queue=0) | stock=10 version=3
02:43:36 [primary] GET /stock -> 200 | stock=10 version=3
```

Secondary log:

```
02:43:35 [secondary] replication applied | stock=10 version=3
02:43:35 [secondary] POST /replicate -> 200 | stock=10 version=3
02:43:36 [secondary] GET /stock -> 200 | stock=10 version=3
```

## Evidence: stale read test (Scenario 2)

I pause replication, then write 9. The primary has 9 right away, but the secondary still says 10. That is the stale read. The status shows 1 update waiting in the queue.

Client:

```
$ python client.py pause
pause ok: {'paused': True}
$ python client.py write 9
write ok: {'replica': 'primary', 'stock': 9, 'version': 4}
$ python client.py read primary
primary: stock=9 version=4
$ python client.py read secondary
secondary: stock=10 version=3
$ python client.py read both
primary:   stock=9 version=4
secondary: stock=10 version=3
Result: DIFFERENT (stale read)
$ python client.py status
status: paused=True pending_updates=1
```

Primary log:

```
02:43:36 [primary] replication paused | stock=10 version=3
02:43:36 [primary] POST /admin/pause-replication -> 200 | stock=10 version=3
02:43:36 [primary] write saved, queued for replication (queue=1) | stock=9 version=4
02:43:36 [primary] PUT /stock -> 200 | stock=9 version=4
02:43:37 [primary] GET /stock -> 200 | stock=9 version=4
02:43:37 [primary] GET /stock -> 200 | stock=9 version=4
02:43:37 [primary] GET /admin/status -> 200 | stock=9 version=4
```

Secondary log (no replicate call came in, so it still has 10):

```
02:43:37 [secondary] GET /stock -> 200 | stock=10 version=3
02:43:37 [secondary] GET /stock -> 200 | stock=10 version=3
```

## Evidence: recovery and convergence (Scenario 3)

I resume replication and wait about 1 second. The waiting update gets sent, the secondary moves to 9, and both replicas match again. The queue is empty.

Client:

```
$ python client.py resume
resume ok: {'paused': False}
$ python client.py read secondary
secondary: stock=9 version=4
$ python client.py read both
primary:   stock=9 version=4
secondary: stock=9 version=4
Result: SAME
$ python client.py status
status: paused=False pending_updates=0
```

Primary log:

```
02:43:43 [primary] replication resumed | stock=9 version=4
02:43:43 [primary] POST /admin/resume-replication -> 200 | stock=9 version=4
02:43:43 [primary] replicated version 4 to secondary (queue=0) | stock=9 version=4
02:43:44 [primary] GET /stock -> 200 | stock=9 version=4
02:43:45 [primary] GET /admin/status -> 200 | stock=9 version=4
```

Secondary log:

```
02:43:43 [secondary] replication applied | stock=9 version=4
02:43:43 [secondary] POST /replicate -> 200 | stock=9 version=4
02:43:44 [secondary] GET /stock -> 200 | stock=9 version=4
02:43:44 [secondary] GET /stock -> 200 | stock=9 version=4
```

## Reflection

I learned that reading from a secondary replica does not always give the newest data. In my test, the primary had stock 9 while the secondary still had 10 because replication was paused.

Reading from replicas is faster and helps spread the work across multiple servers, but the data can be a little old. If the newest value is important, reading from the primary is safer, but it is slower and puts more load on the primary. After I resumed replication, the secondary got the new value and both replicas matched again.
