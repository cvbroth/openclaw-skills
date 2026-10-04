"""Local root-manager/nonroot dual-container + readonly NAS integration.

Role fixtures use real core/stdlibrary CLI, not an OpenClaw daemon or QQ account.
Only disposable volumes and explicitly local desktop-linux Docker are accessed.
"""
import argparse
import json
import subprocess
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="nas-filetools-test:1.2.1")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    docker = ["docker", "--context", "desktop-linux"]
    image, python = args.image, "/opt/nas-filetools/.venv/bin/python"
    prefix = "filetools-v121-test-"+uuid.uuid4().hex[:10]
    volume, nas = prefix+"-workspace", prefix+"-nas"
    roles = [prefix+"-gateway", prefix+"-worker"]
    def run(*argv, payload=None):
        result = subprocess.run([*docker, *argv], input=payload, text=True, capture_output=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr[-4000:] or result.stdout[-4000:])
        return result.stdout.strip()
    def root(code, *argv):
        return run("run", "--rm", "--network", "none", "--user", "0:0", "-e", "PYTHONPATH=/check/src",
                   "-v", str(repo)+":/check:ro", "-v", volume+":/workspace", "-v", nas+":/nas",
                   "--entrypoint", python, image, "-c", code, *argv)
    try:
        run("volume", "create", volume)
        run("volume", "create", nas)
        root("import os;from pathlib import Path;w=Path('/workspace');os.chown(w,10001,10001);os.chmod(w,0o700);"
             "n=Path('/nas');os.chmod(n,0o755);(n/'input.txt').write_text('Readonly NAS original evidence');os.chmod(n/'input.txt',0o444)")
        for role in roles:
            run("run", "-d", "--name", role, "--network", "none", "--user", "10001:10001", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true", "-e", "PYTHONPATH=/check/src", "-v", str(repo)+":/check:ro",
                "-v", volume+":/workspace", "-v", nas+":/nas:ro", "--entrypoint", python, image,
                "-c", "import time;time.sleep(600)")
        assert all(run("exec", role, "id", "-u") == "10001" for role in roles)
        for mask in ("022", "077"):
            marker = ".diagnostic-"+uuid.uuid4().hex
            try:
                metadata = json.loads(root("import os,json,sys;from pathlib import Path;"
                    "from nas_filetools.operations_v12 import diagnostic_marker;os.umask(int(sys.argv[2],8));"
                    "p=Path('/workspace')/sys.argv[1];diagnostic_marker(p,'root',10001,10001);s=p.stat();"
                    "print(json.dumps({'uid':s.st_uid,'gid':s.st_gid,'mode':oct(s.st_mode&511)}))", marker, mask))
                assert metadata == {"uid": 10001, "gid": 10001, "mode": "0o660"}
                for role, before, after in ((roles[0], "root", "gateway"), (roles[1], "gateway", "worker")):
                    run("exec", role, python, "-c", "from pathlib import Path;import sys;p=Path('/workspace')/sys.argv[1];"
                        "assert p.read_text()==sys.argv[2];p.write_text(sys.argv[3])", marker, before, after)
                run("exec", roles[0], python, "-c", "from pathlib import Path;import sys;assert (Path('/workspace')/sys.argv[1]).read_text()=='worker'", marker)
            finally:
                root("import sys;from pathlib import Path;(Path('/workspace')/sys.argv[1]).unlink(missing_ok=True)", marker)
        code = '''import json
from pathlib import Path
from nas_filetools.contracts import Limits,Fault
from nas_filetools.shared_workspace import mapped_store
from nas_filetools.management import register_source
i={'user_id':'chen','agent_id':'chen','session_hash':'a'*64}
p={'workspace':'/workspace','source_roots':{'incoming':{'path':'/nas','kind':'nas'}}}
s=mapped_store(p,'chen',Limits(enabled_agents=('chen',)),'gateway')
r=register_source(s,i,{'source_root':'incoming','source_path':'input.txt'})
assert Path(r['file_reference']['gateway_path']).read_text()=='Readonly NAS original evidence'
reference=register_source(s,i,{'source_root':'incoming','source_path':'input.txt','mode':'reference'})
try:Path('/nas/input.txt').write_text('Forbidden');raise AssertionError('source writable')
except OSError:pass
assert s.files(i,'delete_original',file_id=reference['file_id'])['external_original_deleted'] is False
assert Path('/nas/input.txt').read_text()=='Readonly NAS original evidence'
print(json.dumps({'snapshot':r['file_id'],'reference':reference['file_id']}))
'''
        registered = json.loads(run("exec", roles[0], python, "-c", code))
        run("exec", roles[1], python, "-c", "from pathlib import Path;assert Path('/nas/input.txt').read_text()=='Readonly NAS original evidence';"
            "p=Path('/workspace/filetools/saved/test.md');p.write_text('Worker output stays writable')")
        # A replacement outside both readonly mounts invalidates the registered version.
        version_code = code.replace("print(json.dumps({'snapshot':r['file_id'],'reference':reference['file_id']}))", "print(reference['attachment_id'])")
        version_code = version_code.replace("'mode':'reference'", "'mode':'reference','request_id':'9'*32")
        version_code = version_code.replace("assert s.files(i,'delete_original',file_id=reference['file_id'])['external_original_deleted'] is False", "pass")
        registered_version = run("exec", roles[0], python, "-c", version_code)
        root("from pathlib import Path;p=Path('/nas/input.txt');p.write_text('Changed original version')")
        check = '''import sys
from nas_filetools.shared_workspace import mapped_store
from nas_filetools.contracts import Limits,Fault
i={'user_id':'chen','agent_id':'chen','session_hash':'a'*64}
s=mapped_store({'workspace':'/workspace','source_roots':{'incoming':{'path':'/nas','kind':'nas'}}},'chen',Limits(enabled_agents=('chen',)),'gateway')
try:s.attachment(i,sys.argv[1]);raise AssertionError('changed reference accepted')
except Fault as e:assert e.code=='REFERENCE_CHANGED'
'''
        run("exec", roles[0], python, "-c", check, registered_version)
        assert root("from pathlib import Path;print(len(list(Path('/workspace').glob('.diagnostic-*'))))") == "0"
        report = {"status": "PASSED", "production": "NOT_ACCESSED", "qq_gateway_e2e": "NOT_RUN", "dependency_image": image,
                  "roles": "Linux root manager container + two actual UID10001 role containers; not OpenClaw daemon",
                  "real_checks": ["umask022/077 marker ownership660", "nonroot Gateway/Worker sequential read/write", "marker cleanup",
                                  "actual readonly NAS mounts; snapshot/reference registration", "external remove dereferences only",
                                  "outside change rejects prior reference", "worker saved original entrance writable"], "ids": registered}
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output/"v121-docker-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
    finally:
        for role in roles:
            subprocess.run([*docker, "rm", "-f", role], capture_output=True)
        for name in (volume, nas):
            subprocess.run([*docker, "volume", "rm", name], capture_output=True)


if __name__ == "__main__":
    main()
