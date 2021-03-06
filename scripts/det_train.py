import os, sys, yaml
import hydra
from omegaconf import DictConfig, OmegaConf

# torch
from torchvision import transforms

# others
import pytorch_lightning as pl
from pytorch_lightning.loggers import CSVLogger, TensorBoardLogger, WandbLogger
from pytorch_lightning.callbacks import ModelCheckpoint, EarlyStopping, ModelSummary, DeviceStatsMonitor, TQDMProgressBar

# modules
from pl_jdt.pl.modules.det_module import LitModule
from pl_jdt.pl.datasets.mot import LitDataset
import pl_jdt.utils.utils as utils
import pl_jdt.utils.references.detection.transforms as T

# rich
from rich import pretty, traceback
pretty.install()
traceback.install(suppress=[
    hydra, 
    # pl,
])

# transforms
def get_transforms(train):
    transforms = []
    transforms.append(T.ToTensor())
    if train:
        transforms.append(T.RandomHorizontalFlip(0.5))
    return T.Compose(transforms)

@hydra.main(config_path="../cfg", config_name="config")
def main(cfg : DictConfig) -> None:
    os.environ['HYDRA_FULL_ERROR'] = '1'
    # print(OmegaConf.to_yaml(cfg))
    # init
    project_name = cfg.project.name
    output_path = f"{cfg.project.root_dir}/{cfg.project.output_dir}"
    data_path = f"{cfg.project.data_dir}"
    exp_name = cfg.exp.name
    # exp_path = '{save_dir}/{today}/{curr_time}-{exp_name}-{random_str}'
    # example: ./output/2020-04-24/12-14-test-L1GV1
    exp_path, run_name = utils.exp(output_path, exp_name)

    # set seed
    seed = cfg.exp.seed if 'seed' in cfg.exp.keys() else 42
    pl.seed_everything(seed, workers=True)

    # Dataset
    dataset_kwargs = {
        'batch_size': cfg.exp.train.batch_size if 'batch_size' in cfg.exp.train.keys() else 2,
        'val_batch_size': cfg.exp.val.batch_size if 'val_batch_size' in cfg.exp.val.keys() else cfg.exp.train.batch_size,
        'num_workers': cfg.exp.num_workers if 'num_workers' in cfg.exp.keys() else 4,
        'train_split': cfg.exp.split.train if 'split' in cfg.exp.keys() and 'train' in cfg.exp.split.keys() else None,
        'val_split': cfg.exp.split.val if 'split' in cfg.exp.keys() and 'val' in cfg.exp.split.keys() else None,
        'test_split': cfg.exp.split.test if 'split' in cfg.exp.keys() and 'test' in cfg.exp.split.keys() else None,
    }

    dataset = LitDataset(data_path, get_transforms, **dataset_kwargs)
    dataset.prepare_data()
    dataset.setup()

    # Module
    module = None
    module_kwargs = {
        'len_train_data_loader': len(dataset.train_dataloader()),
    }
    checkpoint_path = cfg.exp.checkpoint_path if 'checkpoint_path' in cfg.exp.keys() else False
    if checkpoint_path:
        module_kwargs.update({
            'checkpoint_path': checkpoint_path,
        })
        module = LitModule.load_from_checkpoint(**module_kwargs)
    else:
        module_kwargs.update({
            'optimizer': cfg.exp.train.optimizer if 'train' in cfg.exp.keys() and 'optimizer' in cfg.exp.train.keys() else {'name': 'sgd', 'params': {'lr': 0.00001, 'weight_decay': 0.0005,'momentum': 0.9}},
            'lr_scheduler': cfg.exp.train.lr_scheduler if 'train' in cfg.exp.keys() and 'lr_scheduler' in cfg.exp.train.keys() else {'name': 'step', 'params': {'step_size': 10, 'gamma': 0.1}},
            'warmup': cfg.exp.train.warmup if 'train' in cfg.exp.keys() and 'warmup' in cfg.exp.train.keys() else False,
        })
        module = LitModule(**module_kwargs)

    # Trainer
    trainer_kwargs = {
        'max_epochs': cfg.exp.max_epochs if 'max_epochs' in cfg.exp.keys() else 10,
        # int: n = check validation set every 1000 training batches
        # float: n = check validation set 1/n times during a training epoch
        # 'val_check_interval': cfg.exp.val_check_interval if 'test' in cfg.exp.keys() and cfg.exp.test and 'val_check_interval' in cfg.exp.keys() else 1.0,
        # int: n = run val every n epoch
        'check_val_every_n_epoch': cfg.exp.check_val_every_n_epoch if 'check_val_every_n_epoch' in cfg.exp.keys() else 2,
        # int: n = log every n steps
        'log_every_n_steps': cfg.exp.log_every_n_steps if 'log_every_n_steps' in cfg.exp.keys() else 200,
        # 'flush_logs_every_n_steps': cfg.exp.flush_logs_every_n_steps if 'flush_logs_every_n_steps' in cfg.exp.keys() else 200,
        # bool: True = run 1 train, val, test batch
        # int: n = run n train, val, test batches
        'fast_dev_run': cfg.exp.fast_dev_run if 'fast_dev_run' in cfg.exp.keys() else False,
        # int: n = check runs n batches of val before training
        'num_sanity_val_steps': cfg.exp.num_sanity_val_steps if 'num_sanity_val_steps' in cfg.exp.keys() else 0,
        # simple, advanced - https://pytorch-lightning.readthedocs.io/en/latest/advanced/profiler.html
        'profiler': cfg.exp.profiler if 'profiler' in cfg.exp.keys() else None,
        # float: n = n/100 of the training data is trained on every epoch
        # int: n = n of the training data is trained on every epoch
        'overfit_batches': cfg.exp.overfit_batches if 'overfit_batches' in cfg.exp.keys() else 0,
        # 'default_root_dir': f'{exp_path}/ckpts',
        # 'max_steps': cfg.exp.train.max_steps if 'max_step' in cfg.exp.train.keys() else 10,
        # 'accumulate_grad_batches': cfg.exp.accumulate_grad_batches if 'accumulate_grad_batches' in cfg.exp.keys() else 1,
        # 'auto_lr_find': cfg.exp.auto_lr_find if 'auto_lr_find' in cfg.exp.keys() else False,
        # 'benchmark': cfg.exp.benchmark if 'benchmark' in cfg.exp.keys() else False,
        # 'deterministic': cfg.exp.deterministic if 'deterministic' in cfg.exp.keys() else False,
    }
    trainer_kwargs.update({
        'devices': 1,
        'accelerator': 'gpu'
    })
    if 'devices' in cfg.exp.keys() and len(cfg.exp.devices) > 1:
            trainer_kwargs.update({
                'devices': len(cfg.exp.devices),
                'accelerator': cfg.exp.accelerator if 'accelerator' in cfg.exp.keys() else 'gpu',
                'strategy': cfg.exp.strategy if 'strategy' in cfg.exp.keys() else 'ddp',
                'amp_backend': cfg.exp.amp_backend if 'amp_backend' in cfg.exp.keys() else 'native',
                'sync_batchnorm': cfg.exp.sync_batchnorm if 'sync_batchnorm' in cfg.exp.keys() else False,
            })
    else: 
        trainer_kwargs.update({
            'devices': cfg.exp.devices if 'devices' in cfg.exp.keys() else [0],
            'accelerator': cfg.exp.accelerator if 'accelerator' in cfg.exp.keys() else 'gpu',
        })
    # Loggers
    loggers = {}
    enabled = {}
    if not trainer_kwargs['fast_dev_run']:
        if 'csv' in cfg.exp.keys() and cfg.exp.csv:
            csv_kwargs = {
                'save_dir': f"{output_path}/csv_logs",
                'name': run_name
            }
            enabled['csv'] = csv_kwargs
            loggers['csv'] = CSVLogger(**csv_kwargs)
        if 'tb' in cfg.exp.keys() and cfg.exp.tb:
            tb_kwargs = {
                'save_dir': f'{output_path}/tb_logs',
                'name': run_name
            }
            enabled['tb'] = tb_kwargs
            loggers['tb'] = TensorBoardLogger(**tb_kwargs)
        if 'wandb' in cfg.exp.keys() and cfg.exp.wandb:
            wandb_kwargs = {
                'project': project_name,
                'name': run_name,
                'save_dir': f'{output_path}'
            }
            enabled['wandb'] = wandb_kwargs
            loggers['wandb'] = WandbLogger(**wandb_kwargs)
    print(f'Enabled loggers:\n{OmegaConf.to_yaml(enabled)}\n\n')

    # callbacks
    callbacks = {}
    enabled = {}
    if not trainer_kwargs['fast_dev_run']:
        progress_bar_kwargs = {
            'refresh_rate': cfg.exp.refresh_rate if 'refresh_rate' in cfg.exp.keys() else 1,
        }
        enabled['progress_bar'] = progress_bar_kwargs
        callbacks['progress_bar'] = TQDMProgressBar(**progress_bar_kwargs)
        if 'checkpoints' in cfg.exp.keys():
            checkpoints_kwargs = {
                'dirpath': cfg.exp.checkpoints.dirpath if 'dirpath' in cfg.exp.checkpoints.keys() else f'{exp_path}/ckpts',
                # 'every_n_epochs': cfg.exp.checkpoints.every_n_epochs if 'every_n_epochs' in cfg.exp.checkpoints.keys() else 1,
                'monitor': cfg.exp.checkpoints.monitor if 'monitor' in cfg.exp.checkpoints.keys() else 'train/epoch/loss',
                # 'filename': 'sample-mnist-{epoch:03d}-{val_loss:.2f}',
            }
            enabled['checkpoints'] = checkpoints_kwargs
            callbacks['checkpoints'] = ModelCheckpoint(**checkpoints_kwargs)
        else:
            checkpoints_kwargs = {
                'dirpath': f'{exp_path}/ckpts',
                'monitor': 'val/epoch/loss',
            }
            enabled['checkpoints'] = checkpoints_kwargs
            callbacks['checkpoints'] = ModelCheckpoint(**checkpoints_kwargs)
        if 'device_stats_monitor' in cfg.exp.keys() and cfg.exp.device_stats_monitor:
            enabled['device_stats_monitor'] = True
            callbacks['device_stats_monitor'] = DeviceStatsMonitor()
        if 'early_stopping' in cfg.exp.keys():
            early_stopping_kwargs = {
                'monitor': cfg.exp.early_stopping.monitor if 'monitor' in cfg.exp.early_stopping.keys() else "train/epoch/loss",
                'patience': cfg.exp.early_stopping.patience if 'patience' in cfg.exp.early_stopping.keys() else 3,
            }
            enabled['early_stopping'] = early_stopping_kwargs
            callbacks['early_stopping'] = EarlyStopping(**early_stopping_kwargs)
        if 'model_summary' in cfg.exp.keys():
            model_summary_kwargs = {
                'max_depth': cfg.exp.model_summary.max_depth if 'max_depth' in cfg.exp.model_summary.keys() else 1,
            }
            enabled['model_summary'] = model_summary_kwargs
            callbacks['model_summary'] = ModelSummary(**model_summary_kwargs)
    print(f'Enabled callbacks:\n{OmegaConf.to_yaml(enabled)}\n\n')

    trainer_kwargs['callbacks'] = [callback for callback in callbacks.keys()]
    trainer_kwargs['logger'] = [logger for logger in loggers.keys()]
    # print(OmegaConf.to_yaml(trainer_kwargs))
    trainer_kwargs['callbacks'] = [callback for callback in callbacks.values()]
    trainer_kwargs['logger'] = [logger for logger in loggers.values()]
    trainer = pl.Trainer(**trainer_kwargs)

    # fit
    trainer.fit(module, dataset.train_dataloader(), dataset.val_dataloader())
if __name__ == "__main__":
    main()