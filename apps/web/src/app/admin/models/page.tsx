"use client";

import { useCallback, useEffect, useState } from "react";

import {
  AdminClient,
  isModelVerified,
  verificationBadgeLabel,
} from "@/lib/admin";
import type { AdminModel } from "@/lib/admin";
import {
  Alert,
  Card,
  Notice,
  cardStyle,
  errorMessage,
  inputClass,
  inputStyle,
} from "@/components/admin/AdminUI";

const CAPS = [
  { key: "cap_responses", label: "Responses" },
  { key: "cap_chat", label: "Chat" },
  { key: "cap_streaming", label: "流式" },
  { key: "cap_tools", label: "工具" },
  { key: "cap_image", label: "图片" },
] as const;

function badgeStyle(model: AdminModel): React.CSSProperties {
  if (isModelVerified(model)) return { background: "rgba(16,185,129,0.15)", color: "#047857" };
  if (model.verification_status === "available")
    return { background: "rgba(245,158,11,0.15)", color: "#92400e" };
  if (model.verification_status === "pending")
    return { background: "var(--surface-muted)", color: "inherit" };
  return { background: "rgba(239,68,68,0.12)", color: "#b91c1c" };
}

function ModelRow({
  model,
  onChanged,
  onError,
}: {
  model: AdminModel;
  onChanged: (updated: AdminModel) => void;
  onError: (msg: string) => void;
}) {
  const [aliases, setAliases] = useState(model.aliases.join(", "));
  const [sortOrder, setSortOrder] = useState(String(model.sort_order));
  const [pinnedGroup, setPinnedGroup] = useState(model.pinned_group ?? "");
  const [caps, setCaps] = useState({
    cap_responses: model.cap_responses,
    cap_chat: model.cap_chat,
    cap_streaming: model.cap_streaming,
    cap_tools: model.cap_tools,
    cap_image: model.cap_image,
  });
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmVerify, setConfirmVerify] = useState(false);
  const [verifyNote, setVerifyNote] = useState<string | null>(null);

  async function patch(
    patch: Parameters<AdminClient["updateModel"]>[1],
  ): Promise<AdminModel | null> {
    setBusy(true);
    try {
      const updated = await new AdminClient().updateModel(model.canonical_name, patch);
      onChanged(updated);
      return updated;
    } catch (err) {
      onError(errorMessage(err));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function saveEdits() {
    const parsed = Number(sortOrder);
    if (!Number.isFinite(parsed)) {
      onError("排序值必须是数字");
      return;
    }
    setSaving(true);
    try {
      const updated = await new AdminClient().updateModel(model.canonical_name, {
        aliases: aliases.split(",").map((a) => a.trim()).filter(Boolean),
        sort_order: parsed,
        pinned_group: pinnedGroup.trim() === "" ? null : pinnedGroup.trim(),
        ...caps,
      });
      onChanged(updated);
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function doVerify() {
    setBusy(true);
    try {
      const updated = await new AdminClient().verifyModel(model.canonical_name);
      setVerifyNote(
        updated.cost_warning ??
          "验证已发送真实请求，费用已按实际用量计入。",
      );
      setConfirmVerify(false);
      onChanged(updated);
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr className="border-t align-top" style={{ borderColor: "var(--border)" }}>
      <td className="px-3 py-3">
        <p className="font-mono text-sm font-medium">{model.canonical_name}</p>
        <p className="mt-1 text-xs opacity-60">
          {model.in_upstream ? "上游有此模型" : "上游无此模型"}
          {model.is_default ? " · 默认模型" : ""}
        </p>
        {model.last_error ? (
          <p className="mt-1 text-xs text-red-600 dark:text-red-400">
            最近错误：{model.last_error}
          </p>
        ) : null}
        {model.last_verified_at ? (
          <p className="mt-1 text-xs opacity-60">最近验证：{model.last_verified_at}</p>
        ) : null}
      </td>
      <td className="px-3 py-3">
        <span
          className="inline-block rounded-full px-2 py-0.5 text-xs font-medium"
          style={badgeStyle(model)}
        >
          {verificationBadgeLabel(model)}
        </span>
        <p className="mt-1 text-xs opacity-60">
          验证方式：{model.verification_method ?? "未验证"}
        </p>
      </td>
      <td className="px-3 py-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={model.enabled}
            disabled={busy}
            onChange={(e) => void patch({ enabled: e.target.checked })}
            aria-label={`启用 ${model.canonical_name}`}
          />
          {model.enabled ? "已启用" : "已停用"}
        </label>
        <button
          type="button"
          disabled={busy || model.is_default}
          onClick={() => void patch({ is_default: true })}
          className="mt-2 rounded-lg border px-2 py-1 text-xs disabled:opacity-50"
          style={{ borderColor: "var(--border)" }}
        >
          {model.is_default ? "当前默认" : "设为默认"}
        </button>
      </td>
      <td className="px-3 py-3">
        <label className="block text-xs opacity-60" htmlFor={`aliases-${model.canonical_name}`}>
          别名（逗号分隔）
        </label>
        <input
          id={`aliases-${model.canonical_name}`}
          className={`${inputClass} mt-1 font-mono`}
          style={inputStyle}
          value={aliases}
          onChange={(e) => setAliases(e.target.value)}
        />
        <div className="mt-2 flex gap-2">
          <label className="flex-1 text-xs opacity-60">
            排序
            <input
              className={`${inputClass} mt-1`}
              style={inputStyle}
              inputMode="numeric"
              aria-label={`排序 ${model.canonical_name}`}
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value)}
            />
          </label>
          <label className="flex-1 text-xs opacity-60">
            固定分组
            <input
              className={`${inputClass} mt-1`}
              style={inputStyle}
              aria-label={`固定分组 ${model.canonical_name}`}
              placeholder="留空为不固定"
              value={pinnedGroup}
              onChange={(e) => setPinnedGroup(e.target.value)}
            />
          </label>
        </div>
        <fieldset className="mt-2">
          <legend className="text-xs opacity-60">能力</legend>
          <div className="mt-1 flex flex-wrap gap-3">
            {CAPS.map((cap) => (
              <label key={cap.key} className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={caps[cap.key]}
                  onChange={(e) =>
                    setCaps((c) => ({ ...c, [cap.key]: e.target.checked }))
                  }
                />
                {cap.label}
              </label>
            ))}
          </div>
        </fieldset>
        <button
          type="button"
          disabled={saving}
          onClick={() => void saveEdits()}
          className="mt-2 rounded-lg px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          style={{ background: "var(--accent)" }}
        >
          {saving ? "保存中…" : "保存修改"}
        </button>
      </td>
      <td className="px-3 py-3">
        {confirmVerify ? (
          <div
            role="alert"
            className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-2 text-xs"
          >
            <p className="font-medium text-amber-700 dark:text-amber-300">
              验证将发送一次真实请求，可能产生 API 费用。
            </p>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void doVerify()}
                className="rounded-lg px-2 py-1 font-medium text-white disabled:opacity-50"
                style={{ background: "var(--accent)" }}
              >
                确认验证
              </button>
              <button
                type="button"
                onClick={() => setConfirmVerify(false)}
                className="rounded-lg border px-2 py-1"
                style={{ borderColor: "var(--border)" }}
              >
                取消
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={() => setConfirmVerify(true)}
            className="rounded-lg border px-3 py-1.5 text-xs disabled:opacity-50"
            style={{ borderColor: "var(--border)" }}
          >
            验证
          </button>
        )}
        {verifyNote ? (
          <p role="status" className="mt-2 text-xs opacity-70">{verifyNote}</p>
        ) : null}
      </td>
    </tr>
  );
}

/**
 * Model center. Pinned models are grouped separately; a model is shown
 * as verified only when verification_status is "available" with a real
 * verification method — never otherwise.
 */
export default function AdminModelsPage() {
  const [models, setModels] = useState<AdminModel[]>([]);
  const [upstreamOnly, setUpstreamOnly] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await new AdminClient().listModels();
      setModels(res.models);
      setUpstreamOnly(res.upstream_only);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function handleChanged(updated: AdminModel) {
    setModels((prev) =>
      prev.map((m) => (m.canonical_name === updated.canonical_name ? updated : m)),
    );
    setNotice(`已更新 ${updated.canonical_name}`);
  }

  const pinned = models.filter((m) => m.pinned_group);
  const rest = models.filter((m) => !m.pinned_group);

  function renderTable(list: AdminModel[]) {
    if (list.length === 0) return <p className="text-sm opacity-60">暂无模型。</p>;
    return (
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead>
            <tr className="text-xs opacity-60">
              <th className="px-3 py-2 font-medium">模型</th>
              <th className="px-3 py-2 font-medium">验证状态</th>
              <th className="px-3 py-2 font-medium">启用 / 默认</th>
              <th className="px-3 py-2 font-medium">别名 / 排序 / 能力</th>
              <th className="px-3 py-2 font-medium">验证</th>
            </tr>
          </thead>
          <tbody>
            {list.map((m) => (
              <ModelRow
                key={m.canonical_name}
                model={m}
                onChanged={handleChanged}
                onError={setError}
              />
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">模型中心</h1>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="rounded-lg border px-3 py-1.5 text-sm disabled:opacity-50"
          style={{ borderColor: "var(--border)" }}
        >
          刷新
        </button>
      </div>
      {loading ? <p className="text-sm opacity-60">正在加载…</p> : null}
      <Alert text={error} />
      <Notice text={notice} />

      {pinned.length > 0 ? (
        <Card title="固定分组模型">
          {renderTable(pinned)}
        </Card>
      ) : null}

      <div className="rounded-2xl border p-4 shadow-sm sm:p-5" style={cardStyle}>
        <h2 className="text-base font-semibold">全部模型</h2>
        <div className="mt-3">{renderTable(rest)}</div>
      </div>

      {upstreamOnly.length > 0 ? (
        <Card title="仅上游有的模型（未接入网关）">
          <ul className="mt-1 flex flex-wrap gap-2">
            {upstreamOnly.map((name) => (
              <li
                key={name}
                className="rounded-full border px-2 py-0.5 font-mono text-xs"
                style={{ borderColor: "var(--border)" }}
              >
                {name}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs opacity-60">
            这些模型存在于上游，但未在网关注册；如需使用请先在网关侧添加。
          </p>
        </Card>
      ) : null}
    </div>
  );
}
