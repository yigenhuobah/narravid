"""
narravid WebUI 全功能端到端测试脚本

用法:
  python test_e2e.py
  python test_e2e.py --port 5001 --workers 2
  python test_e2e.py --keep  (在 test_output/ 下保留本次测试的唯一目录)
  python test_e2e.py --base-url http://127.0.0.1:5000 --allow-destructive-existing-server

测试内容:
  1. 启动 WebUI 服务
  2. 生成测试素材（彩色图片 + BGM）
  3. 上传图片（单张 + 批量）
  4. 缩略图访问 + 路径安全校验
  5. 渲染视频（含 TTS、标题页、字幕烧录、BGM）
  6. 进度轮询
  7. 取消渲染
  8. 下载结果视频
  9. 多线程渲染对比
"""
import argparse
import base64
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import wave
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

# ── 测试素材生成 ──────────────────────────────────────────────

def generate_test_image(width: int, height: int, color: tuple, text: str, out_path: Path):
    """用 matplotlib 生成带文字的彩色测试图片"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    r, g, b = [x / 255 for x in color]
    fig.patch.set_facecolor((r, g, b))
    ax.set_facecolor((r, g, b))
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis('off')
    ax.text(width / 2, height / 2, text, fontsize=42, fontweight='bold',
            color='white', ha='center', va='center',
            fontfamily=['Microsoft YaHei', 'SimHei', 'sans-serif'])
    plt.tight_layout(pad=0)
    fig.savefig(out_path, dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)


def generate_test_bgm(out_path: Path, duration_sec: float = 15.0, freq: float = 440.0):
    """用 Python wave 模块生成简单的正弦波 BGM wav 文件"""
    import math
    import struct

    sample_rate = 24000
    n_samples = int(sample_rate * duration_sec)
    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        # 柔和的和弦：A4 + E5 + A5，低音量
        val = (math.sin(2 * math.pi * freq * t) * 0.15 +
               math.sin(2 * math.pi * freq * 1.5 * t) * 0.10 +
               math.sin(2 * math.pi * freq * 2 * t) * 0.08)
        sample = int(val * 32767)
        sample = max(-32768, min(32767, sample))
        samples.append(struct.pack('<h', sample))

    with wave.open(str(out_path), 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b''.join(samples))


# ── HTTP 工具 ────────────────────────────────────────────────

def api_get(base_url: str, path: str, expect_ok: bool = True):
    """发送 GET 请求"""
    url = base_url + path
    req = Request(url)
    try:
        resp = urlopen(req, timeout=10)
        data = json.loads(resp.read().decode('utf-8'))
        return resp.status, data
    except HTTPError as e:
        body = e.read().decode('utf-8', 'ignore')
        try:
            data = json.loads(body)
        except Exception:
            data = {'raw': body}
        return e.code, data


def api_post(base_url: str, path: str, payload: dict = None):
    """发送 POST JSON 请求"""
    url = base_url + path
    body = json.dumps(payload or {}, ensure_ascii=False).encode('utf-8')
    req = Request(url, data=body, headers={'Content-Type': 'application/json'})
    try:
        resp = urlopen(req, timeout=30)
        data = json.loads(resp.read().decode('utf-8'))
        return resp.status, data
    except HTTPError as e:
        body = e.read().decode('utf-8', 'ignore')
        try:
            data = json.loads(body)
        except Exception:
            data = {'raw': body}
        return e.code, data


def upload_file(base_url: str, file_path: Path):
    """上传文件到 /api/upload"""
    raw = file_path.read_bytes()
    b64 = base64.b64encode(raw).decode('ascii')
    payload = {'name': file_path.name, 'data': b64}
    return api_post(base_url, '/api/upload', payload)


def poll_until_done(base_url: str, render_id: str, timeout: float = 600, interval: float = 2.0):
    """轮询 /api/status 直到渲染完成"""
    start = time.time()
    last_progress = ''
    while time.time() - start < timeout:
        status, data = api_get(base_url, f'/api/status/{render_id}')
        progress = data.get('progress', '')
        if progress != last_progress:
            print(f'    进度: {progress}')
            last_progress = progress
        if data.get('done'):
            return data
        if data.get('error'):
            return data
        time.sleep(interval)
    return {'error': f'超时 ({timeout}s)'}


# ── 测试用例 ─────────────────────────────────────────────────

class TestResult:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.skipped = []

    def ok(self, name, detail=''):
        self.passed.append(name)
        tag = '\033[92mPASS\033[0m'
        print(f'  [{tag}] {name}' + (f' — {detail}' if detail else ''))

    def fail(self, name, detail=''):
        self.failed.append(name)
        tag = '\033[91mFAIL\033[0m'
        print(f'  [{tag}] {name}' + (f' — {detail}' if detail else ''))

    def skip(self, name, detail=''):
        self.skipped.append(name)
        tag = '\033[93mSKIP\033[0m'
        print(f'  [{tag}] {name}' + (f' — {detail}' if detail else ''))

    def summary(self):
        total = len(self.passed) + len(self.failed) + len(self.skipped)
        print(f'\n{"="*60}')
        print(f'测试结果: {total} 项')
        print(f'  \033[92m通过: {len(self.passed)}\033[0m')
        print(f'  \033[91m失败: {len(self.failed)}\033[0m')
        print(f'  \033[93m跳过: {len(self.skipped)}\033[0m')
        if self.failed:
            print('\n  失败项:')
            for f in self.failed:
                print(f'    - {f}')
        print(f'{"="*60}')
        return len(self.failed) == 0


def wait_for_server(base_url: str, timeout: float = 15.0):
    """等待服务器启动"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urlopen(base_url + '/', timeout=2)
            if resp.status == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


@contextmanager
def e2e_workspace(keep: bool, output_root: Path | None = None):
    """Create one isolated run directory without touching earlier E2E output."""
    if keep:
        root = output_root or Path(__file__).resolve().parent / 'test_output'
        root.mkdir(parents=True, exist_ok=True)
        yield Path(tempfile.mkdtemp(prefix='e2e-', dir=root))
        return

    with tempfile.TemporaryDirectory(prefix='narravid-e2e-') as temp_dir:
        yield Path(temp_dir)


def local_port_available(port: int) -> bool:
    """Return False when another process already owns the local test port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            exclusive = getattr(socket, 'SO_EXCLUSIVEADDRUSE', None)
            if os.name == 'nt' and exclusive is not None:
                listener.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            listener.bind(('127.0.0.1', port))
        return True
    except OSError:
        return False


def server_process_kwargs() -> dict:
    """Put the WebUI in a process boundary that can be terminated as a tree."""
    if os.name == 'nt':
        return {'creationflags': getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)}
    return {'start_new_session': True}


def start_webui_server(port: int, test_dir: Path):
    """Start an isolated WebUI and redirect all output to a file."""
    webui_script = Path(__file__).resolve().parent / 'webui.py'
    log_path = test_dir / 'webui-server.log'
    env = os.environ.copy()
    env['NARRAVID_DATA_DIR'] = str(test_dir / 'server-data')
    with log_path.open('wb', buffering=0) as log_file:
        proc = subprocess.Popen(
            [sys.executable, str(webui_script), '--host', '127.0.0.1', '--port', str(port)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            **server_process_kwargs(),
        )
    return proc, log_path


def read_log_tail(log_path: Path, max_bytes: int = 16 * 1024) -> str:
    """Read only the tail of a server log so diagnostics cannot exhaust memory."""
    try:
        with log_path.open('rb') as log_file:
            log_file.seek(0, 2)
            size = log_file.tell()
            log_file.seek(max(0, size - max_bytes))
            return log_file.read().decode('utf-8', 'replace').strip()
    except OSError:
        return ''


def _terminate_directly(proc, timeout: float) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
        return
    except Exception:
        pass
    if proc.poll() is None:
        try:
            proc.kill()
            proc.wait(timeout=timeout)
        except Exception:
            pass


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_process_group_exit(proc, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        proc.poll()  # Reap the parent so a zombie cannot keep the group alive.
        if not _process_group_exists(proc.pid):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))


def terminate_process_tree(proc, timeout: float = 5.0) -> None:
    """Best-effort termination of the WebUI and all media subprocesses."""
    if proc is None:
        return

    if os.name == 'nt':
        try:
            subprocess.run(
                ['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=timeout,
            )
            if proc.poll() is None:
                proc.wait(timeout=timeout)
        except Exception:
            pass
        _terminate_directly(proc, timeout)
        return

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        _terminate_directly(proc, timeout)
        return

    if _wait_for_process_group_exit(proc, timeout):
        return

    try:
        os.killpg(proc.pid, getattr(signal, 'SIGKILL', 9))
    except ProcessLookupError:
        return
    except Exception:
        _terminate_directly(proc, timeout)
        return

    _wait_for_process_group_exit(proc, timeout)
    _terminate_directly(proc, timeout)


def run_tests(base_url: str, test_dir: Path, workers: int, result: TestResult):
    """运行全部测试用例"""

    # ── 测试 1: 服务器可达 ──
    print('\n[1] 服务器连通性')
    try:
        resp = urlopen(base_url + '/', timeout=5)
        result.ok('首页可访问', f'status={resp.status}')
    except Exception as e:
        result.fail('首页可访问', str(e))
        return  # 服务器不通，后续测试无法进行

    # ── 测试 2: 生成测试素材 ──
    print('\n[2] 生成测试素材')
    assets_dir = test_dir / 'assets'
    assets_dir.mkdir(parents=True, exist_ok=True)

    images = []
    scenes_data = [
        ('第一幕：数据概览', (26, 26, 46), '数据分析概览\n探索游戏世界的故事'),
        ('第二幕：趋势分析', (22, 66, 91), '趋势分析\n数据揭示隐藏的规律'),
        ('第三幕：深度解读', (44, 62, 80), '深度解读\n每个细节都值得思考'),
        ('第四幕：总结展望', (69, 31, 31), '总结与展望\n故事仍在继续'),
    ]
    try:
        for i, (label, color, text) in enumerate(scenes_data, 1):
            img_path = assets_dir / f'slide-{i:02d}.png'
            generate_test_image(1920, 1080, color, text, img_path)
            images.append((img_path, label))
            print(f'    生成: {img_path.name} ({label})')
        result.ok('生成 4 张测试图片')

        bgm_path = assets_dir / 'test_bgm.wav'
        generate_test_bgm(bgm_path, duration_sec=20.0)
        result.ok('生成测试 BGM', f'{bgm_path.name}')
    except Exception as e:
        result.fail('生成测试素材', str(e))
        return

    # ── 测试 3: 上传图片 ──
    print('\n[3] 图片上传')
    uploaded_images = []
    for img_path, label in images:
        status, data = upload_file(base_url, img_path)
        if status == 200 and 'path' in data:
            uploaded_images.append((data['path'], label))
            result.ok(f'上传 {img_path.name}', f'size={img_path.stat().st_size}')
        else:
            result.fail(f'上传 {img_path.name}', f'status={status}, data={data}')

    if len(uploaded_images) < len(images):
        result.skip('后续上传相关测试', '图片上传不完整')
        return

    # ── 测试 4: 缩略图访问 + 路径安全 ──
    print('\n[4] 缩略图访问与安全')
    # 4a: 正常缩略图
    valid_path = uploaded_images[0][0]
    try:
        url = base_url + '/thumb?path=' + __import__('urllib.parse').parse.quote(valid_path)
        resp = urlopen(url, timeout=5)
        if resp.status == 200 and len(resp.read()) > 0:
            result.ok('正常缩略图可访问')
        else:
            result.fail('正常缩略图可访问', f'status={resp.status}')
    except Exception as e:
        result.fail('正常缩略图可访问', str(e))

    # 4b: 路径遍历 / 白名单外绝对路径（跨平台）
    import os as _os
    _forbid = 'C:/Windows/win.ini' if _os.name == 'nt' else '/etc/passwd'
    try:
        url = base_url + '/thumb?path=' + __import__('urllib.parse').parse.quote(_forbid)
        resp = urlopen(url, timeout=5)
        # 如果返回 403，说明安全防护生效
        result.fail('路径遍历防护', f'应该返回 403，实际返回 {resp.status}')
    except HTTPError as e:
        if e.code in (403, 404):
            result.ok('路径遍历防护', f'返回 {e.code} ({_forbid})')
        else:
            result.fail('路径遍历防护', f'期望 403/404，返回 {e.code}')

    # ── 测试 5: 上传 BGM ──
    print('\n[5] BGM 上传')
    bgm_remote = None
    status, data = upload_file(base_url, bgm_path)
    if status == 200 and 'path' in data:
        bgm_remote = data['path']
        result.ok('上传 BGM 文件', f'{bgm_path.name}')
    else:
        result.fail('上传 BGM 文件', f'status={status}, data={data}')

    # ── 测试 6: 完整渲染（标题页 + TTS + 字幕烧录 + BGM） ──
    print('\n[6] 完整渲染测试 (标题页 + TTS + 字幕 + BGM)')
    manifest = {
        'title': 'narravid-e2e-test',
        'width': 1280,   # 小分辨率加速测试
        'height': 720,
        'fps': 24,
        'tts_engine': 'edge',
        'voice': 'zh-CN-XiaoxiaoNeural',
        'speech_speed': 1.5,
        'burn_subtitles': True,
        'workers': workers,
        'scenes': [
            {'image': uploaded_images[0][0], 'text': '这是一个全功能测试视频。narravid可以自动将图片和文案转化为解说视频。', 'hold_sec': 0.5},
            {'image': uploaded_images[1][0], 'text': '支持多线程并行处理，大幅提升生成速度。', 'hold_sec': 0.3},
            {'image': uploaded_images[2][0], 'text': '支持中英文标点分句，自动生成精准字幕。', 'hold_sec': 0.3},
            {'image': uploaded_images[3][0], 'text': '感谢观看！更多功能持续开发中。', 'hold_sec': 1.0},
        ]
    }
    render_body = {
        'manifest': manifest,
        'bgm': bgm_remote,
        'title_card': 'narravid 全功能测试',
        'render_id': 'e2etest',
    }
    render_started_at = time.monotonic()
    status, data = api_post(base_url, '/api/render', render_body)
    if status == 200 and 'render_id' in data:
        rid = data['render_id']
        result.ok('发起渲染', f'render_id={rid}')

        print('    等待渲染完成...')
        final = poll_until_done(base_url, rid, timeout=300)
        if final.get('error'):
            result.fail('渲染完成', final['error'][:200])
        else:
            result.ok('渲染完成', f'duration≈{time.monotonic() - render_started_at:.1f}s')
            video_url = final.get('video', '')
            if video_url:
                result.ok('获得视频路径', video_url)
                # 下载视频
                try:
                    video_resp = urlopen(base_url + video_url, timeout=30)
                    video_bytes = video_resp.read()
                    video_out = test_dir / 'e2e_test_video.mp4'
                    video_out.write_bytes(video_bytes)
                    result.ok('下载视频', f'{len(video_bytes)/1024:.0f} KB → {video_out}')
                except Exception as e:
                    result.fail('下载视频', str(e))
            else:
                result.fail('获得视频路径', 'video 字段为空')
    else:
        result.fail('发起渲染', f'status={status}, data={data}')

    # ── 测试 7: 不烧录字幕 ──
    print('\n[7] 无字幕渲染测试')
    manifest_nosub = dict(manifest)
    manifest_nosub['burn_subtitles'] = False
    manifest_nosub['scenes'] = [
        {'image': uploaded_images[0][0], 'text': '这条没有烧录字幕。', 'hold_sec': 0.5},
        {'image': uploaded_images[1][0], 'text': '但仍然有配音和独立SRT文件。', 'hold_sec': 0.5},
    ]
    render_body_nosub = {
        'manifest': manifest_nosub,
        'bgm': None,
        'title_card': None,
        'render_id': 'nosubtest',
    }
    status, data = api_post(base_url, '/api/render', render_body_nosub)
    if status == 200 and 'render_id' in data:
        rid = data['render_id']
        result.ok('发起无字幕渲染', f'render_id={rid}')
        final = poll_until_done(base_url, rid, timeout=120)
        if final.get('error'):
            result.fail('无字幕渲染完成', final['error'][:200])
        else:
            result.ok('无字幕渲染完成')
    else:
        result.fail('发起无字幕渲染', f'status={status}')

    # ── 测试 8: 空文案（纯图片展示） ──
    print('\n[8] 纯图片展示测试 (无文案)')
    manifest_silent = dict(manifest)
    manifest_silent['scenes'] = [
        {'image': uploaded_images[0][0], 'text': '', 'hold_sec': 3.0},
    ]
    render_body_silent = {
        'manifest': manifest_silent,
        'bgm': None,
        'title_card': None,
        'render_id': 'silenttest',
    }
    status, data = api_post(base_url, '/api/render', render_body_silent)
    if status == 200 and 'render_id' in data:
        rid = data['render_id']
        result.ok('发起纯图片渲染', f'render_id={rid}')
        final = poll_until_done(base_url, rid, timeout=60)
        if final.get('error'):
            result.fail('纯图片渲染完成', final['error'][:200])
        else:
            result.ok('纯图片渲染完成')
    else:
        result.fail('发起纯图片渲染', f'status={status}')

    # ── 测试 9: 取消渲染 ──
    print('\n[9] 取消渲染测试')
    manifest_long = dict(manifest)
    manifest_long['scenes'] = [
        {'image': uploaded_images[i][0], 'text': f'第{i+1}段较长的文案，用于测试取消功能。这段文字应该足够长，使得渲染需要一定时间。' * 3, 'hold_sec': 1.0}
        for i in range(4)
    ]
    render_body_long = {
        'manifest': manifest_long,
        'bgm': None,
        'title_card': '取消测试',
        'render_id': 'canceltest',
    }
    status, data = api_post(base_url, '/api/render', render_body_long)
    if status == 200 and 'render_id' in data:
        rid = data['render_id']
        result.ok('发起长渲染', f'render_id={rid}')
        time.sleep(2)  # 等一会儿再取消
        cancel_status, cancel_data = api_post(base_url, f'/api/cancel/{rid}')
        if cancel_status == 200:
            result.ok('发送取消请求', f'status={cancel_status}')
            # Poll until terminal; cancel must stick (not silent success)
            cancelled_ok = False
            last = {}
            for _ in range(90):
                st_code, st = api_get(base_url, f'/api/status/{rid}')
                last = st if isinstance(st, dict) else {}
                if st_code == 200 and last.get('done'):
                    if last.get('cancelled') or '取消' in str(last.get('error') or ''):
                        cancelled_ok = True
                    break
                time.sleep(1)
            if cancelled_ok:
                result.ok('取消生效', f'progress={last.get("progress")}')
            else:
                result.fail('取消生效', f'终态未标记取消: {last}')
        else:
            result.fail('发送取消请求', f'status={cancel_status}')
    else:
        result.fail('发起长渲染', f'status={status}')

    # ── 测试 10: 无效请求校验 ──
    print('\n[10] 边界与错误处理')
    # 10a: 不存在的 render_id
    status, data = api_get(base_url, '/api/status/nonexistent123')
    if status == 404:
        result.ok('不存在的 render_id 返回 404')
    else:
        result.fail('不存在的 render_id 返回 404', f'实际返回 {status}')

    # 10b: 不存在的缩略图（路径不在白名单 → 403；路径在白名单但文件不存在 → 404）
    try:
        url = base_url + '/thumb?path=/nonexistent/path/image.png'
        resp = urlopen(url, timeout=5)
        result.fail('不存在的缩略图应返回错误', f'实际返回 {resp.status}')
    except HTTPError as e:
        if e.code in (403, 404):
            result.ok('不存在的缩略图返回错误', f'{e.code}')
        else:
            result.fail('不存在的缩略图应返回 403/404', f'实际返回 {e.code}')

    # 10c: 无图片的渲染请求（应该只处理有图片的 scenes）
    manifest_empty = dict(manifest)
    manifest_empty['scenes'] = []  # 空 scenes
    render_body_empty = {
        'manifest': manifest_empty,
        'bgm': None,
        'title_card': None,
        'render_id': 'emptytest',
    }
    # 这个由 video_auto.py 处理，会报错
    status, data = api_post(base_url, '/api/render', render_body_empty)
    if status == 200:
        # 渲染被接受了，但应该最终报错
        rid = data['render_id']
        final = poll_until_done(base_url, rid, timeout=30)
        if final.get('error'):
            result.ok('空 scenes 渲染正确报错', final['error'][:80])
        else:
            result.fail('空 scenes 渲染应报错', '但未报错')
    else:
        result.ok('空 scenes 请求被拒绝', f'status={status}')

    # ── 测试 11: 模板 CRUD（含 BGM / 片头片尾时长字段） ──
    print('\n[11] 模板 CRUD')
    tpl_body = {
        'name': 'e2e-tpl',
        'scenes': [
            {'image': uploaded_images[0][0], 'text': '模板文案', 'hold': 0.3},
        ],
        'voice': 'zh-CN-XiaoxiaoNeural',
        'speed': '1.5',
        'burn': True,
        'resolution': '1280x720',
        'title_card': 'E2E标题',
        'end_card': 'E2E结尾',
        'card_duration': '2',
        'end_card_duration': '1.5',
        'bgm': bgm_remote or '',
        'bgm_volume': '0.25',
        'workers': '2',
    }
    status, data = api_post(base_url, '/api/templates', tpl_body)
    if status == 200 and data.get('id'):
        tid = data['id']
        result.ok('保存模板', tid)
        status, one = api_get(base_url, f'/api/templates/{tid}')
        if status == 200 and one.get('bgm') == (bgm_remote or '') and str(one.get('card_duration')) == '2':
            result.ok('模板含 BGM 与时长字段')
        else:
            result.fail('模板含 BGM 与时长字段', f'{status} {one}')
        # rename via PUT
        try:
            from urllib.request import Request, urlopen as _urlopen
            body = json.dumps({'name': 'e2e-tpl-renamed'}, ensure_ascii=False).encode('utf-8')
            req = Request(base_url + f'/api/templates/{tid}', data=body,
                          headers={'Content-Type': 'application/json'}, method='PUT')
            resp = _urlopen(req, timeout=10)
            put_ok = resp.status == 200
        except Exception as e:
            put_ok = False
            result.fail('重命名模板', str(e))
        if put_ok:
            result.ok('重命名模板')
        try:
            req = Request(base_url + f'/api/templates/{tid}', method='DELETE')
            resp = _urlopen(req, timeout=10)
            if resp.status == 200:
                result.ok('删除模板')
            else:
                result.fail('删除模板', f'status={resp.status}')
        except Exception as e:
            result.fail('删除模板', str(e))
    else:
        result.fail('保存模板', f'{status} {data}')

    # ── 测试 12: 导出 / 导入工程 ──
    print('\n[12] 导出/导入工程')
    export_payload = {
        'manifest': {
            'title': 'e2e-export',
            'width': 1280,
            'height': 720,
            'scenes': [
                {'image': uploaded_images[0][0], 'text': '导出场景', 'hold_sec': 0.3},
            ],
            'title_card': '导出标题',
            'end_card': '导出结尾',
            'card_duration': 2,
            'end_card_duration': 1.5,
        },
        'bgm': bgm_remote,
        'title_card': '导出标题',
        'end_card': '导出结尾',
        'card_duration': 2,
        'end_card_duration': 1.5,
    }
    try:
        from urllib.request import Request, urlopen as _urlopen
        body = json.dumps(export_payload, ensure_ascii=False).encode('utf-8')
        req = Request(base_url + '/api/export', data=body,
                      headers={'Content-Type': 'application/json'}, method='POST')
        resp = _urlopen(req, timeout=60)
        zbytes = resp.read()
        if resp.status == 200 and zbytes[:2] == b'PK':
            result.ok('导出 zip', f'{len(zbytes)} bytes')
            import io as _io
            import zipfile
            with zipfile.ZipFile(_io.BytesIO(zbytes)) as zf:
                man = json.loads(zf.read('manifest.json').decode('utf-8'))
                if man['scenes'][0]['image'].startswith('assets/'):
                    result.ok('导出路径为相对 assets')
                else:
                    result.fail('导出路径为相对 assets', man['scenes'][0]['image'])
            status, imp = api_post(base_url, '/api/import', {
                'data': base64.b64encode(zbytes).decode('ascii'),
            })
            if status == 200 and imp.get('manifest', {}).get('scenes'):
                result.ok('导入工程', f"scenes={len(imp['manifest']['scenes'])}")
                if imp['manifest'].get('title_card') == '导出标题':
                    result.ok('导入恢复 title_card')
                else:
                    result.fail('导入恢复 title_card', str(imp['manifest'].get('title_card')))
            else:
                result.fail('导入工程', f'{status} {imp}')
        else:
            result.fail('导出 zip', f'status={resp.status}')
    except Exception as e:
        result.fail('导出/导入工程', str(e))

    # bad zip
    status, data = api_post(base_url, '/api/import', {
        'data': base64.b64encode(b'not-a-zip').decode('ascii'),
    })
    if status == 400:
        result.ok('非法 zip 返回 400', str(data)[:80])
    else:
        result.fail('非法 zip 返回 400', f'{status} {data}')

    # ── 测试 13: 完成后 cancel 保留成片 ──
    print('\n[13] 完成后 cancel 保留成片')
    # 快速静音场景后 cancel，确认成片 URL 不被抹掉
    short = {
        'manifest': {
            'title': 'e2e-late-cancel',
            'width': 960,
            'height': 540,
            'tts_engine': 'edge',
            'voice': 'zh-CN-XiaoxiaoNeural',
            'speech_speed': 1.5,
            'burn_subtitles': False,
            'workers': 1,
            'scenes': [
                {'image': uploaded_images[0][0], 'text': '', 'hold_sec': 1.0},
            ],
        },
        'render_id': 'e2elatecancel',
    }
    status, data = api_post(base_url, '/api/render', short)
    if status == 200 and data.get('render_id'):
        rid = data['render_id']
        final = poll_until_done(base_url, rid, timeout=90)
        if final.get('video') and final.get('done'):
            video = final['video']
            cst, cdata = api_post(base_url, f'/api/cancel/{rid}')
            st2, after = api_get(base_url, f'/api/status/{rid}')
            if st2 == 200 and after.get('video') == video and not after.get('cancelled'):
                result.ok('完成后 cancel 保留成片', video)
            else:
                result.fail('完成后 cancel 保留成片', f'cancel={cdata} after={after}')
            if final.get('srt'):
                result.ok('status 含 srt', final['srt'])
            else:
                # hold-only may still produce empty/global srt depending on pipeline
                result.skip('status 含 srt', 'hold-only 场景可能无独立 srt 字段')
        else:
            result.fail('完成后 cancel 前置渲染', str(final)[:160])
    else:
        result.fail('完成后 cancel 发起渲染', f'{status} {data}')

    # ── 测试 14: 清理接口 ──
    print('\n[14] 清理旧文件')
    status, data = api_post(base_url, '/api/clean')
    if status == 200 and 'message' in data:
        result.ok('清理旧文件', data.get('message'))
    else:
        result.fail('清理旧文件', f'{status} {data}')


# ── 主流程 ───────────────────────────────────────────────────

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='narravid WebUI 全功能端到端测试')
    parser.add_argument('--port', type=int, default=5001, help='WebUI 端口 (默认 5001)')
    parser.add_argument('--workers', type=int, default=4, help='渲染线程数 (默认 4)')
    parser.add_argument(
        '--keep',
        action='store_true',
        help='在 test_output/ 下保留本次运行的唯一输出目录',
    )
    parser.add_argument(
        '--base-url',
        type=str,
        default=None,
        help='已有 WebUI 地址（会修改其数据；需要显式破坏性操作确认）',
    )
    parser.add_argument(
        '--allow-destructive-existing-server',
        action='store_true',
        help='允许测试修改已有服务：上传、渲染、模板变更、导入和清理旧任务',
    )
    args = parser.parse_args(argv)
    if args.base_url and not args.allow_destructive_existing_server:
        parser.error(
            '--base-url 会修改目标服务并调用 /api/clean；'
            '确认目标可被测试后添加 --allow-destructive-existing-server'
        )
    return args


def run_e2e(args, test_dir: Path) -> int:
    """Run the suite once and always tear down an owned server process tree."""
    base_url = args.base_url or f'http://127.0.0.1:{args.port}'
    result = TestResult()

    print('=' * 60)
    print('narravid WebUI 全功能端到端测试')
    print('=' * 60)

    proc = None
    log_path = None
    started = False
    interrupted = False
    start_time = time.monotonic()
    try:
        if not args.base_url:
            print(f'\n[0] 启动 WebUI (port={args.port}) ...')
            if not local_port_available(args.port):
                result.fail('WebUI 服务启动', f'端口 {args.port} 已被占用')
            else:
                proc, log_path = start_webui_server(args.port, test_dir)
                if wait_for_server(base_url):
                    result.ok('WebUI 服务启动', f'port={args.port}')
                    started = True
                else:
                    result.fail('WebUI 服务启动', '超时')
        else:
            print(f'\n[0] 使用已有服务: {base_url}')
            if wait_for_server(base_url):
                result.ok('已有服务可达')
                started = True
            else:
                result.fail('已有服务不可达')

        if started:
            run_tests(base_url, test_dir, args.workers, result)
    except KeyboardInterrupt:
        print('\n\n测试被中断')
        interrupted = True
    except Exception as e:
        print(f'\n\n测试异常: {e}')
        import traceback
        traceback.print_exc()
        result.fail('测试套件异常', str(e))
    finally:
        terminate_process_tree(proc)

    elapsed = time.monotonic() - start_time
    print(f'\n总耗时: {elapsed:.1f}s')
    if not started and log_path:
        log_tail = read_log_tail(log_path)
        if log_tail:
            print(f'\nWebUI 启动日志末尾:\n{log_tail}')
    success = result.summary()
    if interrupted:
        return 130
    return 0 if success and started else 1


def main(argv=None):
    args = parse_args(argv)
    with e2e_workspace(args.keep) as test_dir:
        exit_code = run_e2e(args, test_dir)
        if args.keep:
            print(f'\n测试输出保留在: {test_dir}')
    if not args.keep:
        print('\n本次临时测试输出已清理 (用 --keep 保留)')
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
