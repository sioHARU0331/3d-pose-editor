# A PC 3Dポーズ編集ツール開発

最初に `handoff/3D_POSE_DEVELOPMENT_HANDOFF.md` を読んでください。

## 開発に使うもの

- 実VRM: `model/AvatarSample_B_clean_hands_v3.vrm`
- 再利用ポーズ: `poses/fortune_think_pose.json`
- 現行ツールの最新版控え: `legacy_live_fortune/`
- VSeeFace連携処理の参照: `integration_reference/vsf_controller.py`

ルート直下の既存 `index.html` と `config.json` は上書きせず残しています。既存 `index.html` には未コミット変更があるため、内容を保護しています。今後の正式基盤は簡易マネキンの拡張ではなく、上記の実VRMを読み込む編集画面として開発してください。

A PCでは実VRMの表示、ボーン選択、手指を含む編集UI、JSON保存・読込まで進められます。VSeeFaceへの実送信と見た目の一致確認はB PCで行います。

`integration_reference/vsf_controller.py` は接続仕様を確認するための控えです。このフォルダ単体でのVSeeFace実機テスト用途ではありません。
