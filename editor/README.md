# 実VRMポーズエディタ（Aローカル開発版）

旧Canvasマネキンとは別の正式基盤候補です。`../model/AvatarSample_B_clean_hands_v3.vrm` を直接読み、右肩・右腕・右手・右手15指関節をVRM Humanoidのnormalized boneで編集します。

## 起動

```powershell
cd editor
pnpm install
pnpm dev
```

表示された `http://127.0.0.1:5173/` を開きます。ファイルを直接開く方式では動作しません。

## JSON

- 保存形式は `schema=vrm-pose-editor`, `version=1`。
- 値はnormalized Humanoid boneのrest quaternionに対するlocal Euler差分（度、XYZ順）です。
- 従来の `RightHand: [x,y,z]` 形式も読み込めます。
- Aでは「payloadを生成」は表示だけで、VSeeFaceへ送信しません。

## Bで確定する項目

カメラの手の面名称、本人左右、VMCの各軸・方向、指15関節、JSON往復、トラッキング競合はVSeeFace実機で確認するまで未確定です。UI上にも明記しています。

## B実機・3骨方向確認

1. `integration_reference/vsf_controller.py` と同じ3骨許可変更を、Bで実際に起動するcontrollerへ反映して再起動します。
2. エディタの「B実機・3骨方向確認」で、右手首→右人差し指付け根→右親指付け根を1回ずつ押します。
3. 各ボタンは対象骨だけへエディタlocal Y +30°を送り、記録欄へ骨名・軸・角度・payload・応答を表示します。
4. 各確認後に「テスト前へ戻す・送信終了」を押します。
5. VSeeFaceでは「同じ方向／逆方向／別軸」のどれかだけを記録します。A側では一致判定しません。