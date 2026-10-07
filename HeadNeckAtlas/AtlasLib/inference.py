"""Subprocess contract for the pinned TotalSegmentator 2.14.0 runtime."""
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import time
import traceback
from .bundle import dump_json, sha256
from .catalog import TASKS

MODEL_VERSION = '2.14.0'
WEIGHT_DIRS = {'head_glands_cavities': 'Dataset775_head_glands_cavities_492subj',
               'head_muscles': 'Dataset777_head_muscles_492subj'}
CROP_WEIGHT_DIR = 'Dataset298_TotalSegmentator_total_6mm_1559subj'


def build_request(input_path, output_path, task, device, allow_download):
    if task not in TASKS or device not in ('cpu', 'gpu') or type(allow_download) is not bool:
        raise ValueError('无效任务、设备或下载选项。')
    input_path = Path(input_path).absolute()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    output_path = Path(output_path).absolute()
    if input_path == output_path or output_path.exists():
        raise ValueError('推理输出必须使用新的文件。')
    return {'input': str(input_path), 'output': str(output_path), 'task': task,
            'device': device, 'allow_download': allow_download, 'fast': False}


def run_worker(request_path):
    request_path = Path(request_path)
    response_path = request_path.with_name('response.json')
    start = time.monotonic()
    response = {'status': 'failed', 'started_utc': datetime.now(timezone.utc).isoformat()}
    try:
        raw = json.loads(request_path.read_text(encoding='utf-8'))
        request = build_request(raw['input'], raw['output'], raw['task'], raw['device'], raw['allow_download'])
        version = importlib.metadata.version('TotalSegmentator')
        if version != MODEL_VERSION:
            raise RuntimeError(f'需要 TotalSegmentator {MODEL_VERSION}，当前为 {version}。')
        if not request['allow_download']:
            # Guard the entire child, including crop weights and telemetry, against network.
            import socket
            def refuse_network(*args, **kwargs):
                raise RuntimeError('未允许下载；需要先准备模型权重。')
            socket.socket.connect = refuse_network
            socket.create_connection = refuse_network
        import torch
        if request['device'] == 'gpu' and not torch.cuda.is_available():
            raise RuntimeError('CUDA GPU 不可用，请明确选择 CPU。')
        from totalsegmentator.config import get_weights_dir
        weights_root = Path(get_weights_dir())
        required_weights = [weights_root / WEIGHT_DIRS[request['task']], weights_root / CROP_WEIGHT_DIR]
        if not request['allow_download']:
            for weight_dir in required_weights:
                if not list(weight_dir.rglob('*.pth')):
                    raise RuntimeError('缺少模型或裁剪权重；先下载权重或勾选允许下载。')
        from totalsegmentator.map_to_binary import class_map
        if request['task'] not in class_map:
            raise RuntimeError('当前模型未提供所选任务。')
        from totalsegmentator.python_api import totalsegmentator
        # Disable anonymous statistics for this worker without editing global settings.
        import totalsegmentator.python_api as api
        if hasattr(api, 'send_usage_stats'):
            api.send_usage_stats = lambda *args, **kwargs: None
        print(f"开始 {request['task']} / {request['device']}", flush=True)
        totalsegmentator(input=Path(request['input']), output=Path(request['output']),
                        task=request['task'], device=request['device'], fast=False,
                        ml=True, nr_thr_saving=1, nr_thr_resamp=1)
        import nibabel as nib
        output_image = nib.load(request['output'])
        if len(output_image.shape) != 3:
            raise RuntimeError('分割输出不是三维影像。')
        response.update(status='success', request=request, model_version=version,
                        torch_version=torch.__version__, class_map=class_map[request['task']],
                        device_name=(torch.cuda.get_device_name(0) if request['device'] == 'gpu' else 'CPU'),
                        weights={file.relative_to(weights_root).as_posix(): sha256(file)
                                 for weight_dir in required_weights for file in weight_dir.rglob('*.pth')})
    except Exception as exc:
        response['error'] = str(exc)
        print(traceback.format_exc(), flush=True)
    response['elapsed_seconds'] = time.monotonic() - start
    dump_json(response_path, response)
    return 0 if response['status'] == 'success' else 1
