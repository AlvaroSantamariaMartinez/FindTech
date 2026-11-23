"""Bucle de entrenamiento de TopoNet.

    python -m toponet.nn.train --data data/dataset --epochs 60 --out checkpoints/toponet_unet.pt

Incluye:
  * partición train/validación reproducible
  * aumentación por simetrías (espejos y cambio y<->z)
  * AdamW + calentamiento lineal + decaimiento coseno del learning rate
  * recorte de gradiente
  * validación cada época, guardado del mejor modelo y "early stopping"
  * registro CSV (para dibujar curvas) y reanudación (--resume)

Teoría: `guia/06-sistema-entrenamiento.md`.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time

import numpy as np
import torch
from torch.utils.data import DataLoader

from .dataset import TopologyDataset, list_samples, split_files
from .features import FEATURE_NAMES
from .losses import LossWeights, batch_metrics, topo_loss
from .model import TopoNetUNet3D, count_parameters, pad_to_multiple, save_checkpoint


def set_seed(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)


def lr_at(step: int, total: int, warmup: int, base_lr: float, min_lr: float) -> float:
    if step < warmup:
        return base_lr * (step + 1) / warmup
    t = (step - warmup) / max(1, total - warmup)
    return min_lr + 0.5 * (base_lr - min_lr) * (1 + math.cos(math.pi * t))


def run_epoch(model, loader, weights, device, optimizer=None, sched=None, clip=1.0):
    train = optimizer is not None
    model.train(train)
    agg = {"loss": 0.0, "bce": 0.0, "dice": 0.0, "vol": 0.0, "tv": 0.0, "iou": 0.0, "mae": 0.0, "vol_err": 0.0}
    n = 0
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        x, (X, Y, Z) = pad_to_multiple(x, model.multiple)
        y, _ = pad_to_multiple(y, model.multiple)
        with torch.set_grad_enabled(train):
            logits = model(x)
            loss, parts = topo_loss(logits, y, x, weights)
        if train:
            if sched is not None:
                for g in optimizer.param_groups:
                    g["lr"] = sched()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), clip)
            optimizer.step()
        m = batch_metrics(logits.detach(), y, x)
        b = x.shape[0]
        agg["loss"] += loss.item() * b
        for k, v in {**parts, **m}.items():
            agg[k] += v * b
        n += b
    return {k: v / max(n, 1) for k, v in agg.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Entrena TopoNet (U-Net 3D)")
    ap.add_argument("--data", default="data/dataset")
    ap.add_argument("--out", default="checkpoints/toponet_unet.pt")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--min-lr", type=float, default=5e-5)
    ap.add_argument("--weight-decay", type=float, default=1e-4)
    ap.add_argument("--warmup-epochs", type=float, default=2)
    ap.add_argument("--base", type=int, default=16, help="canales del primer nivel")
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--val-fraction", type=float, default=0.1)
    ap.add_argument("--patience", type=int, default=15, help="épocas sin mejora antes de parar")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--threads", type=int, default=0, help="hilos de CPU para PyTorch (0 = auto)")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--w-bce", type=float, default=1.0)
    ap.add_argument("--w-dice", type=float, default=0.5)
    ap.add_argument("--w-vol", type=float, default=5.0)
    ap.add_argument("--w-tv", type=float, default=0.02)
    ap.add_argument("--energy-alpha", type=float, default=2.0)
    a = ap.parse_args(argv)

    set_seed(a.seed)
    if a.threads:
        torch.set_num_threads(a.threads)
    device = ("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu") \
        if a.device == "auto" else a.device

    files = list_samples(a.data)
    if len(files) < 4:
        raise SystemExit(f"Hacen falta más muestras en {a.data} (hay {len(files)}). Ejecuta generate_data.")
    tr_files, va_files = split_files(files, a.val_fraction, a.seed)
    train_ds = TopologyDataset(tr_files, augment=True, seed=a.seed)
    val_ds = TopologyDataset(va_files, augment=False)
    train_dl = DataLoader(train_ds, batch_size=a.batch, shuffle=True, drop_last=len(train_ds) > a.batch)
    val_dl = DataLoader(val_ds, batch_size=a.batch, shuffle=False)

    model = TopoNetUNet3D(in_channels=len(FEATURE_NAMES), base=a.base, depth=a.depth, dropout=a.dropout).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=a.weight_decay)
    weights = LossWeights(a.w_bce, a.w_dice, a.w_vol, a.w_tv, a.energy_alpha)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    log_path = os.path.splitext(a.out)[0] + "_log.csv"
    state_path = os.path.splitext(a.out)[0] + "_state.pt"
    start_epoch, best, bad = 0, float("inf"), 0
    if a.resume and os.path.exists(state_path):
        st = torch.load(state_path, map_location=device, weights_only=False)
        model.load_state_dict(st["model"])
        opt.load_state_dict(st["opt"])
        start_epoch, best, bad = st["epoch"] + 1, st["best"], st["bad"]
        print(f"Reanudando desde la época {start_epoch}")

    steps_per_epoch = max(1, len(train_dl))
    total_steps = a.epochs * steps_per_epoch
    warmup = int(a.warmup_epochs * steps_per_epoch)
    step = [start_epoch * steps_per_epoch]

    def sched():
        lr = lr_at(step[0], total_steps, warmup, a.lr, a.min_lr)
        step[0] += 1
        return lr

    print(f"Dispositivo: {device} | parámetros: {count_parameters(model):,} | "
          f"train: {len(train_ds)}  val: {len(val_ds)} | forma: {tuple(train_ds.X.shape[2:])}")
    new_log = not (a.resume and os.path.exists(log_path))
    with open(log_path, "w" if new_log else "a", newline="") as fh:
        wr = csv.writer(fh)
        if new_log:
            wr.writerow(["epoch", "lr", "train_loss", "val_loss", "train_iou", "val_iou", "val_mae", "val_vol_err",
                         "val_bce", "val_dice", "time_s"])
        for ep in range(start_epoch, a.epochs):
            t0 = time.time()
            tr = run_epoch(model, train_dl, weights, device, opt, sched)
            va = run_epoch(model, val_dl, weights, device)
            lr = opt.param_groups[0]["lr"]
            dt = time.time() - t0
            wr.writerow([ep, f"{lr:.2e}", f"{tr['loss']:.5f}", f"{va['loss']:.5f}", f"{tr['iou']:.4f}", f"{va['iou']:.4f}",
                         f"{va['mae']:.4f}", f"{va['vol_err']:.4f}", f"{va['bce']:.4f}", f"{va['dice']:.4f}", f"{dt:.1f}"])
            fh.flush()
            mark = ""
            if va["loss"] < best:
                best, bad = va["loss"], 0
                save_checkpoint(a.out, model, {
                    "epoch": ep, "val": va, "features": FEATURE_NAMES,
                    "train_shape": list(train_ds.X.shape[2:]), "args": vars(a),
                    "n_train": len(train_ds),
                })
                mark = "  * mejor"
            else:
                bad += 1
            print(f"época {ep:3d} | lr {lr:.1e} | train {tr['loss']:.4f} (IoU {tr['iou']:.3f}) | "
                  f"val {va['loss']:.4f} (IoU {va['iou']:.3f}, MAE {va['mae']:.3f}, ΔV {va['vol_err']:.3f}) | "
                  f"{dt:.1f}s{mark}", flush=True)
            torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "epoch": ep, "best": best, "bad": bad},
                       state_path)
            if bad >= a.patience:
                print(f"Early stopping: {a.patience} épocas sin mejorar.")
                break
    print(f"Mejor pérdida de validación: {best:.4f} -> {a.out}")
    with open(os.path.splitext(a.out)[0] + "_args.json", "w") as fh:
        json.dump(vars(a), fh, indent=2)


if __name__ == "__main__":
    main()
