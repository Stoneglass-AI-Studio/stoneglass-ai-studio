# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit first UI profile. Never infer another checkpoint's resource bundle."""
from stoneglass.inference.contracts import ModelSpec
from stoneglass.inference.resources import read_manifest, invalid

CHECKPOINT_SHA256 = 'c379d154eb476b67b390e31463c41c79ac9e766466315408886ebb7faa2ea098'
RESOURCE_HASHES = {'model_index.json': '6d7b93508390ab91ac5bfbe4aeb4dc2d83f7bb1b05fb069d714b5b0c75f70d44',
 'unet/config.json': '30ebc70750223e59006f7f2b4e1e6c102570aa19a9c4ae3e1fbe7591332dbae6',
 'vae/config.json': '0b331c8ac22ded5f9997a144a575c1d113d6169aff262c353f39015bd24a6264',
 'text_encoder/config.json': '39b8b2e4b1949e36969caa425b6c81c68bace99198dd9078ce05d16ad401fe7f',
 'text_encoder_2/config.json': 'a892d1c3a69a7e9247a24de2bc1d5891e3109a54696e53be20093af671072c34',
 'scheduler/scheduler_config.json': 'af3e45a949aff8b8341ab8b811429ec03fee857a700a1d9477363e4fff9666e2',
 'tokenizer/vocab.json': 'e089ad92ba36837a0d31433e555c8f45fe601ab5c221d4f607ded32d9f7a4349',
 'tokenizer/merges.txt': '9fd691f7c8039210e0fced15865466c65820d09b63988b0174bfe25de299051a',
 'tokenizer/tokenizer_config.json': '19d7b034cb0cc3ce9766c2231373ab8aa8991fc72e2c8f76558bfaae3de0d563',
 'tokenizer/special_tokens_map.json': 'c4864a9376a8401918425bed71fc14fc0e81f9b59ec45c1cf96cccb2df508eac',
 'tokenizer_2/vocab.json': 'e089ad92ba36837a0d31433e555c8f45fe601ab5c221d4f607ded32d9f7a4349',
 'tokenizer_2/merges.txt': '9fd691f7c8039210e0fced15865466c65820d09b63988b0174bfe25de299051a',
 'tokenizer_2/tokenizer_config.json': 'c9d23941f76a41cbd50eda9290f57be7828f0a7a677939e9ef181f7e12bd1bdf',
 'tokenizer_2/special_tokens_map.json': 'f118ab3a983206e4f32583448de6bd6aae4ee21869135cef1f5848a753cdaab6'}


def require_reviewed_profile(model: ModelSpec) -> None:
    if model.resource_manifest is None:
        raise invalid("Select this checkpoint's complete local resource manifest.")
    manifest = read_manifest(model.resource_manifest)
    if manifest.checkpoint_sha256 != CHECKPOINT_SHA256 or {r.path:r.sha256 for r in manifest.resources} != RESOURCE_HASHES:
        raise invalid("The initial UI supports only the reviewed AlbedoBase XL v3.1-Large checkpoint and its exact validated resource bundle. Other profiles are unavailable.")
