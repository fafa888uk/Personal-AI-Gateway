"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  AdminClient,
  changePasswordErrorMessage,
  validatePasswordChange,
} from "@/lib/admin";
import type { AdminSettings, PricingRule } from "@/lib/admin";
import {
  Alert,
  Card,
  Notice,
  errorMessage,
  inputClass,
  inputStyle,
  primaryButtonClass,
  primaryButtonStyle,
} from "@/components/admin/AdminUI";

function numberOrNull(value: string): number | null {
  const v = value.trim();
  if (v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/**
 * Settings: global budgets, per-model pricing rules (with the
 * server-reported updated_at — never faked), retention policy, and
 * the version/release info reported by GET /api/v1/app/version.
 */
export default function AdminSettingsPage() {
  const router = useRouter();
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [dailyBudget, setDailyBudget] = useState("");
  const [monthlyBudget, setMonthlyBudget] = useState("");
  const [retentionDays, setRetentionDays] = useState("");
  const [pricing, setPricing] = useState<PricingRule[]>([]);

  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwSaving, setPwSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const s = await new AdminClient().getSettings();
      setSettings(s);
      setDailyBudget(s.budgets.daily_usd != null ? String(s.budgets.daily_usd) : "");
      setMonthlyBudget(s.budgets.monthly_usd != null ? String(s.budgets.monthly_usd) : "");
      setRetentionDays(s.retention_days != null ? String(s.retention_days) : "");
      setPricing(s.pricing ?? []);
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

  async function saveAll() {
    setError(null);
    setSaving(true);
    try {
      const updated = await new AdminClient().updateSettings({
        budgets: {
          daily_usd: numberOrNull(dailyBudget),
          monthly_usd: numberOrNull(monthlyBudget),
        },
        retention_days: numberOrNull(retentionDays),
        pricing,
      });
      setSettings(updated);
      setNotice("设置已保存");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  function updatePricing(index: number, field: keyof PricingRule, value: string) {
    setPricing((prev) =>
      prev.map((rule, i) =>
        i === index
          ? { ...rule, [field]: field === "model" ? value : numberOrNull(value) }
          : rule,
      ),
    );
  }

  /**
   * Rotate the admin password. The backend revokes every session
   * (including this one), so on success the form is cleared and the
   * user is sent back to /admin/login with a flag for the
   * "use the new password" notice.
   */
  async function submitPasswordChange() {
    setPwError(null);
    const validation = validatePasswordChange(currentPw, newPw, confirmPw);
    if (validation) {
      setPwError(validation);
      return;
    }
    setPwSaving(true);
    try {
      await new AdminClient().changePassword(currentPw, newPw);
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
      try {
        sessionStorage.setItem("pag_password_changed", "1");
      } catch {
        // Storage unavailable: the login page simply shows no notice.
      }
      router.replace("/admin/login");
    } catch (err) {
      setPwError(changePasswordErrorMessage(err));
    } finally {
      setPwSaving(false);
    }
  }

  const version = settings?.version as
    | { configured?: boolean; version?: string | null; gateway_version?: string | null; note?: string | null }
    | null
    | undefined;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">设置</h1>
      {loading ? <p className="text-sm opacity-60">正在加载…</p> : null}
      <Alert text={error} />
      <Notice text={notice} />

      <Card title="全局预算（美元）">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-sm font-medium">
            每日预算上限（留空为不限）
            <input
              className={`${inputClass} mt-1`}
              style={inputStyle}
              inputMode="decimal"
              value={dailyBudget}
              onChange={(e) => setDailyBudget(e.target.value)}
              placeholder="例如 5"
            />
          </label>
          <label className="text-sm font-medium">
            每月预算上限（留空为不限）
            <input
              className={`${inputClass} mt-1`}
              style={inputStyle}
              inputMode="decimal"
              value={monthlyBudget}
              onChange={(e) => setMonthlyBudget(e.target.value)}
              placeholder="例如 50"
            />
          </label>
        </div>
      </Card>

      <Card title="保留策略">
        <label className="block max-w-xs text-sm font-medium">
          请求记录保留天数（留空为服务器默认）
          <input
            className={`${inputClass} mt-1`}
            style={inputStyle}
            inputMode="numeric"
            value={retentionDays}
            onChange={(e) => setRetentionDays(e.target.value)}
            placeholder="例如 90"
          />
        </label>
      </Card>

      <Card title="定价规则（美元 / 每百万 Token）">
        {pricing.length === 0 ? (
          <p className="text-sm opacity-60">暂无定价规则；费用将显示为「价格未配置」。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr className="text-xs opacity-60">
                  <th className="px-3 py-2 font-medium">模型</th>
                  <th className="px-3 py-2 font-medium">输入</th>
                  <th className="px-3 py-2 font-medium">输出</th>
                  <th className="px-3 py-2 font-medium">缓存输入</th>
                  <th className="px-3 py-2 font-medium">推理</th>
                  <th className="px-3 py-2 font-medium">最近更新</th>
                </tr>
              </thead>
              <tbody>
                {pricing.map((rule, i) => (
                  <tr key={rule.model} className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-2 font-mono">{rule.model}</td>
                    {(
                      [
                        "input_usd_per_1m",
                        "output_usd_per_1m",
                        "cached_input_usd_per_1m",
                        "reasoning_usd_per_1m",
                      ] as const
                    ).map((field) => (
                      <td key={field} className="px-3 py-2">
                        <input
                          className={`${inputClass} w-24`}
                          style={inputStyle}
                          inputMode="decimal"
                          aria-label={`${rule.model} ${field}`}
                          value={rule[field] != null ? String(rule[field]) : ""}
                          onChange={(e) => updatePricing(i, field, e.target.value)}
                        />
                      </td>
                    ))}
                    <td className="px-3 py-2 text-xs opacity-70">
                      {rule.updated_at ?? "未知"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div>
        <button
          type="button"
          disabled={saving}
          onClick={() => void saveAll()}
          className={primaryButtonClass}
          style={primaryButtonStyle()}
        >
          {saving ? "保存中…" : "保存全部设置"}
        </button>
      </div>

      <Card title="修改密码">
        <p className="text-sm opacity-70">
          修改后将吊销全部登录会话（含当前会话），须使用新密码重新登录。新密码至少 12 位。
        </p>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className="text-sm font-medium">
            现密码
            <input
              className={`${inputClass} mt-1`}
              style={inputStyle}
              type="password"
              autoComplete="current-password"
              value={currentPw}
              onChange={(e) => setCurrentPw(e.target.value)}
            />
          </label>
          <label className="text-sm font-medium">
            新密码
            <input
              className={`${inputClass} mt-1`}
              style={inputStyle}
              type="password"
              autoComplete="new-password"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
            />
          </label>
          <label className="text-sm font-medium">
            确认新密码
            <input
              className={`${inputClass} mt-1`}
              style={inputStyle}
              type="password"
              autoComplete="new-password"
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
            />
          </label>
        </div>
        {pwError ? (
          <div className="mt-3">
            <Alert text={pwError} />
          </div>
        ) : null}
        <div className="mt-3">
          <button
            type="button"
            disabled={pwSaving}
            onClick={() => void submitPasswordChange()}
            className={primaryButtonClass}
            style={primaryButtonStyle()}
          >
            {pwSaving ? "正在修改…" : "修改密码"}
          </button>
        </div>
      </Card>

      <Card title="版本与发布信息">
        {settings == null ? (
          <p className="text-sm opacity-60">加载中…</p>
        ) : version == null ? (
          <p className="text-sm opacity-60">服务器未返回版本信息。</p>
        ) : version.configured === false ? (
          <p className="text-sm opacity-70">
            未配置发布信息（服务器无版本数据）。请勿以此为准判断当前版本。
          </p>
        ) : (
          <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="opacity-60">网关版本</dt>
              <dd className="font-mono">{version.gateway_version ?? version.version ?? "未知"}</dd>
            </div>
            <div>
              <dt className="opacity-60">发布版本</dt>
              <dd className="font-mono">{version.version ?? "未知"}</dd>
            </div>
            {version.note ? (
              <div className="sm:col-span-2">
                <dt className="opacity-60">说明</dt>
                <dd>{version.note}</dd>
              </div>
            ) : null}
          </dl>
        )}
      </Card>
    </div>
  );
}
