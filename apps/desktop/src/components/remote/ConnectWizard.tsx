import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { inputCls } from "@/components/settings/inputCls";
import { connectRemoteHost, inspectRemoteHostKey, listSshHosts, pairRemoteHostKey, unpairRemoteHostKey } from "@/lib/tauri";
import { useSshStore } from "@/lib/ssh";
import { isGatewayWeb } from "@/lib/webMode";

export function ConnectWizard({ onConnected }: { onConnected?: (host: string, pinnedNode?: string) => void }) {
  const { t } = useTranslation("session", { keyPrefix: "discovery.remote" });
  const [host, setHost] = useState("");
  const [label, setLabel] = useState("");
  const [method, setMethod] = useState<"password" | "key" | "proxyjump">("password");
  const [jumpHost, setJumpHost] = useState("");
  const [hosts, setHosts] = useState<string[]>([]);
  const [importing, setImporting] = useState(false);
  const [fingerprint, setFingerprint] = useState<string>();
  const [connected, setConnected] = useState<{ host: string; pinnedNode?: string; paired: boolean }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const hostKeyTone = "default";
  useEffect(() => { void listSshHosts().then(setHosts).catch(() => undefined); }, []);

  const connect = async (verified: string) => {
    setFingerprint(undefined);
    setBusy(true);
    setError(undefined);
    try {
      const result = await connectRemoteHost(host.trim(), { fingerprint: verified, method, label: label.trim() || undefined, jumpHost: method === "proxyjump" ? jumpHost.trim() : undefined });
      if (result.needsSignIn && !isGatewayWeb) await useSshStore.getState().connect(host.trim());
      if (!result.connected) throw new Error(t("signInNeeded"));
      setConnected({ host: host.trim(), pinnedNode: result.pinnedNode, paired: false });
      onConnected?.(host.trim(), result.pinnedNode);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  const inspect = async () => {
    setBusy(true);
    setError(undefined);
    try {
      const key = await inspectRemoteHostKey(host.trim());
      if (!key.fingerprint.startsWith("SHA256:")) throw new Error(t("invalidFingerprint"));
      if (key.trusted) await connect(key.fingerprint);
      else setFingerprint(key.fingerprint);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  const pair = async (unpair: boolean) => {
    if (!connected) return;
    setBusy(true);
    setError(undefined);
    try {
      if (unpair) {
        const result = await unpairRemoteHostKey(connected.host);
        if (!result.unpaired) throw new Error(t("unpairFailed"));
        setConnected({ ...connected, paired: false });
      } else {
        const result = await pairRemoteHostKey(connected.host);
        if (!result.paired) throw new Error(t("pairFailed"));
        setConnected({ ...connected, paired: true, pinnedNode: result.pinnedNode ?? connected.pinnedNode });
      }
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };

  return <section className="space-y-3 rounded-xl border border-border p-3" aria-label={t("connectTitle")}>
    <h3 className="font-medium">{t("connectTitle")}</h3>
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void inspect(); }}>
      <fieldset disabled={busy || !!fingerprint} className="space-y-3">
        <button type="button" className="text-sm text-accent" onClick={() => setImporting(!importing)}>{t("importHosts")}</button>
        {importing && <label className="block text-sm">{t("savedHost")}<select className={inputCls("mt-1 w-full")} value={hosts.includes(host) ? host : ""} onChange={(e) => { setHost(e.target.value); setConnected(undefined); }}>
          <option value="">{t("chooseHost")}</option>{hosts.map((h) => <option key={h} value={h}>{h}</option>)}
        </select>{hosts.length === 0 && <span className="text-xs text-muted">{t("noHosts")}</span>}</label>}
        <label className="block text-sm">{t("serverAddress")}<input required value={host} placeholder={t("addressPlaceholder")} className={inputCls("mt-1 w-full")} onChange={(e) => { setHost(e.target.value); setConnected(undefined); }} /></label>
        <label className="block text-sm">{t("signInMethod")}<select value={method} className={inputCls("mt-1 w-full")} onChange={(e) => setMethod(e.target.value as typeof method)}>
          <option value="password">{t("password")}</option><option value="key">{t("existingKey")}</option><option value="proxyjump">{t("proxyJump")}</option>
        </select></label>
        {method === "proxyjump" && <label className="block text-sm">{t("jumpHost")}<input required value={jumpHost} className={inputCls("mt-1 w-full")} onChange={(e) => setJumpHost(e.target.value)} /></label>}
        <label className="block text-sm">{t("serverLabel")}<input value={label} className={inputCls("mt-1 w-full")} onChange={(e) => setLabel(e.target.value)} /></label>
        <button type="submit" disabled={!host.trim() || busy} className="rounded bg-accent px-3 py-2 text-sm text-white">{t((busy ? "working" : "connect"))}</button>
      </fieldset>
    </form>
    {fingerprint && <ConfirmDialog tone={hostKeyTone} title={t("verifyTitle")} body={t("verifyFingerprint", { host, fingerprint })} confirmLabel={t("verified")} onConfirm={() => void connect(fingerprint)} onCancel={() => setFingerprint(undefined)} />}
    {connected && <div className="space-y-2 text-sm" role="status">
      <p>{connected.pinnedNode ? t("pinnedNode", { node: connected.pinnedNode }) : connected.host}</p>
      <button type="button" disabled={busy} className="rounded border border-border px-3 py-1" onClick={() => void pair(connected.paired)}>{t((connected.paired ? "unpair" : "pair"))}</button>
    </div>}
    {error && <p role="alert" className="text-sm text-error">{t("connectionError", { error })}</p>}
  </section>;
}
