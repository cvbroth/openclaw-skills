"""Operator-only local Docker test: two roles, real shared volumes/socket/core. No QQ/Gateway E2E."""
import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    repository = Path(__file__).resolve().parents[1]
    prefix = "nas-filetools-local-test-"+uuid.uuid4().hex[:10]
    docker = ["docker", "--context", "desktop-linux"]
    image = "nas-filetools-test:1.2.0"
    python = "/opt/nas-filetools/.venv/bin/python"
    identity = {"user_id": "chen", "agent_id": "chen", "session_hash": "a"*64}
    names = [prefix+suffix for suffix in ("-worker", "-gateway")]
    volumes = [prefix+suffix for suffix in ("-chen", "-main", "-socket", "-control")]
    def run(*command, payload=None):
        value = subprocess.run([*docker, *command], input=payload, text=True, capture_output=True, timeout=180)
        if value.returncode:
            raise RuntimeError(value.stderr[-4000:] or value.stdout[-4000:])
        return value.stdout.strip()
    def mount(source, destination, readonly=False):
        return ["--mount", f"type=bind,src={source},dst={destination}"+(",readonly" if readonly else "")]
    base = ["--network", "none", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "--pids-limit", "96", "--cpus", "2", "--memory", "4g"]
    limits = {"enabled_agents": ["main", "chen"], "script_isolation": "landlock"}
    gateway = {"limits": limits, "workspaces": {a: {"workspace": f"/gateway/{a}"} for a in ("main", "chen")}}
    worker = {"limits": limits, "workspaces": {a: {"workspace": f"/gateway/{a}", "service_root": f"/workspaces/{a}/filetools"} for a in ("main", "chen")}}
    (output/"gateway.json").write_text(json.dumps(gateway))
    (output/"worker.json").write_text(json.dumps(worker))
    def manager(operation, params, actor=identity):
        response = run("exec", "-i", names[1], python, "-I", "-S", "/check/scripts/filetools_manage.py",
            "--config", "/test/gateway.json", payload=json.dumps({"identity": actor, "operation": operation, "params": params}))
        return json.loads(response)
    def request(operation, params):
        code = "import sys,json;sys.path.insert(0,'/check/src');from nas_filetools.cli import UnixConnection;c=UnixConnection('/run/nas-filetools/service.sock');p=sys.stdin.read();c.request('POST','/v1/tool',body=p,headers={'Content-Type':'application/json'});r=c.getresponse();print(r.read().decode());c.close()"
        return json.loads(run("exec", "-i", names[1], python, "-I", "-S", "-c", code,
            payload=json.dumps({"identity": identity, "operation": operation, "params": params})))
    try:
        for volume in volumes:
            run("volume", "create", volume)
        for volume in volumes:
            code = "import os;from pathlib import Path;p=Path('/volume');os.chown(p,10001,10001);os.chmod(p,0o770);"
            if volume.endswith(("-chen", "-main")):
                code += "f=p/'filetools';f.mkdir();os.chown(f,10001,10001);os.chmod(f,0o770);(p/'notes.txt').write_text('Cedar two-container evidence');os.chown(p/'notes.txt',10001,10001)"
            run("run", "--rm", "--network", "none", "--user", "0:0", "-v", volume+":/volume", "--entrypoint", python, image, "-c", code)
        run("run", "-d", "--name", names[1], *base, *mount(repository, "/check", True), *mount(output, "/test", True),
            "-v", volumes[0]+":/gateway/chen", "-v", volumes[1]+":/gateway/main", "-v", volumes[2]+":/run/nas-filetools",
            "--entrypoint", python, image, "-c", "import time;time.sleep(600)")
        run("run", "-d", "--name", names[0], *base, *mount(repository, "/check", True), *mount(output, "/test", True),
            "--mount", f"type=volume,src={volumes[0]},dst=/workspaces/chen/filetools,volume-subpath=filetools",
            "--mount", f"type=volume,src={volumes[1]},dst=/workspaces/main/filetools,volume-subpath=filetools",
            "-v", volumes[2]+":/run/nas-filetools", "-v", volumes[3]+":/control", "-e", "PYTHONPATH=/check/src",
            "--entrypoint", "/opt/nas-filetools/.venv/bin/nas-filetools", image, "serve", "--root", "/control", "--config", "/test/worker.json")
        for _ in range(100):
            if run("exec", names[1], python, "-c", "from pathlib import Path;print(Path('/run/nas-filetools/service.sock').exists())") == "True":
                break
            time.sleep(.1)
        registered = manager("register", {"source_path": "notes.txt"})
        assert registered["status"] == "REGISTERED", registered
        code = "import os\nfrom pathlib import Path\nfrom openpyxl import Workbook\nPath('report.md').write_text('# Report\\n'+Path(os.environ['FILETOOLS_INPUT']).read_text())\nw=Workbook();w.active['A1']=42;w.save('result.xlsx')"
        job = request("python", {"attachment_id": registered["attachment_id"], "code": code,
            "description": "real two-container shared output", "outputs": ["report.md", "result.xlsx"],
            "checks": [{"file": "result.xlsx", "sheet": "Sheet", "cell": "A1", "equals": 42}]})
        for _ in range(200):
            result = request("status", {"job_id": job["job_id"]})
            if result["status"] not in ("QUEUED", "RUNNING"):
                break
            time.sleep(.05)
        assert result["status"] == "SUCCEEDED", result
        outputs = [a for a in result["artifacts"] if a["kind"] == "output"]
        code = "import sys,json,zipfile,hashlib;from pathlib import Path;files=json.load(sys.stdin);proof=[]\nfor a in files:\n p=Path(a['gateway_path']);assert p.is_file();assert hashlib.file_digest(p.open('rb'),'sha256').hexdigest()==a['sha256'];\n if p.suffix=='.md': assert 'Cedar' in p.read_text()\n if p.suffix=='.xlsx':\n  with zipfile.ZipFile(p) as z: assert '<v>42</v>' in z.read('xl/worksheets/sheet1.xml').decode()\n proof.append({'path':str(p),'sha256':a['sha256']})\nprint(json.dumps(proof))"
        retrieved = json.loads(run("exec", "-i", names[1], python, "-I", "-S", "-c", code, payload=json.dumps(outputs)))
        md = next(a for a in outputs if a["file"].endswith(".md"))
        saved = manager("files", {"action": "save", "job_id": job["job_id"], "artifact_id": md["artifact_id"]})
        manager("files", {"action": "delete_cache", "job_id": job["job_id"]})
        read = manager("files", {"action": "saved_read", "saved_id": saved["saved_id"], "artifact_id": md["artifact_id"]})
        assert "Cedar" in read["text"], read
        other = manager("files", {"action": "select", "file_id": registered["file_id"]}, {**identity, "agent_id": "main"})
        assert other["status"] == "ERROR", other
        inspection = json.loads(run("inspect", names[0]))[0]
        destinations = [m["Destination"] for m in inspection["Mounts"]]
        assert not any(p in destinations for p in ("/gateway", "/gateway/chen", "/home/node/.openclaw"))
        report = {"status": "PASSED", "environment": "local Docker desktop-linux", "gateway_role": "stdlib manager fixture, not OpenClaw daemon",
            "real_checks": ["same UID/GID shared volumes", "Unix HTTP IDs-only control", "Linux isolated Python MD+XLSX", "Gateway ordinary read/hash/XLSX cell", "independent saved after cache cleanup", "cross-Agent denied", "worker mounts only Agent filetools subdirectories"],
            "worker_mount_destinations": destinations, "retrieved_outputs": retrieved, "qq_delivery": "NOT_RUN", "production": "NOT_ACCESSED"}
        (output/"two-container.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        for name in names:
            subprocess.run([*docker, "rm", "-f", name], capture_output=True)
        for volume in volumes:
            subprocess.run([*docker, "volume", "rm", volume], capture_output=True)


if __name__ == "__main__":
    main()
