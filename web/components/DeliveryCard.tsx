"use client";

import { pretty } from "@/lib/api";

/** Which platform, which fallback, which language and script, and the message in each channel's exact shape. */
export default function DeliveryCard({ delivery }: { delivery: any }) {
  if (!delivery) return null;
  const { provider, same_channel_backup: backup, fallback, language, message, fallback_message: fbMsg, preview } = delivery;
  return (
    <section className="panel" style={{ marginBottom: 16 }}>
      <h3>Delivery plan</h3>
      <div className="grid g3">
        <div>
          <div className="muted" style={{ fontSize: 12 }}>Channel · platform</div>
          <div className="ink" style={{ fontWeight: 700 }}>{pretty(delivery.channel)} · {provider?.name ?? "no platform enabled"}</div>
          {provider && <div style={{ fontSize: 13 }}>{provider.why}</div>}
          {provider && !provider.configured && <span className="badge" style={{ marginTop: 4, display: "inline-block" }}>needs credentials</span>}
          {backup && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Same-channel backup: {backup.name}</div>}
        </div>
        <div>
          <div className="muted" style={{ fontSize: 12 }}>Language · script</div>
          <div className="ink" style={{ fontWeight: 700 }}>{language?.template_language} · {language?.script} <span className="mono">{language?.locale}</span></div>
          <div style={{ fontSize: 13 }}>{language?.why}</div>
          {message?.note && <div className="notice" style={{ marginTop: 6 }}>{message.note}</div>}
        </div>
        <div>
          <div className="muted" style={{ fontSize: 12 }}>Fallback</div>
          {fallback ? (
            <>
              <div className="ink" style={{ fontWeight: 700 }}>{pretty(fallback.channel)} · {fallback.provider?.name ?? "no platform"}</div>
              <div style={{ fontSize: 13 }}>{fallback.rule}</div>
            </>
          ) : <div className="muted" style={{ fontSize: 13 }}>No fallback channel with consent</div>}
        </div>
      </div>

      <div className="grid g2" style={{ marginTop: 14 }}>
        <div>
          <h3>Message ({message?.template_language})</h3>
          <div className="quote">{message?.body}</div>
          {message?.whatsapp_template && <p className="mono" style={{ marginTop: 6 }}>WhatsApp template {message.whatsapp_template.name} · language {message.whatsapp_template.language}</p>}
          {message?.sms && <p className="mono" style={{ marginTop: 6 }}>SMS {message.sms.encoding} · {message.sms.chars} chars · {message.sms.segments} segment(s) · DLT {message.sms.dlt_template_id}{message.sms.note ? ` · ${message.sms.note}` : ""}</p>}
          {message?.push && <p className="mono" style={{ marginTop: 6 }}>Push title “{message.push.title}”</p>}
          {fbMsg && <><div className="muted" style={{ fontSize: 12, marginTop: 10 }}>If it falls back to {pretty(fallback.channel)}:</div><div className="quote">{fbMsg.body}</div>
            {fbMsg.sms && <p className="mono">SMS {fbMsg.sms.encoding} · {fbMsg.sms.segments} segment(s)</p>}</>}
        </div>
        <div>
          <h3>Request a sender would make</h3>
          <pre className="mono" style={{ background: "#F9FAFB", border: "1px solid #E5E7EB", padding: 10, overflowX: "auto", maxHeight: 260, margin: 0 }}>
            {JSON.stringify(preview, null, 2)}
          </pre>
          <p className="muted" style={{ fontSize: 12 }}>Nothing is sent from here. Secrets are never shown; placeholders in braces come from your config.</p>
        </div>
      </div>
    </section>
  );
}
