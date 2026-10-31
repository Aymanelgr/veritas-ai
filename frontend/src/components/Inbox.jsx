import { markNotificationRead } from "../api.js";
import { relativeTime } from "../format.js";
import { IconInbox } from "../icons.jsx";

// Messages delivered by the n8n workflows (review needed, daily reminders).
export default function Inbox({ notifications, onChange }) {
  const unread = notifications.filter((n) => !n.read).length;
  return (
    <section className="panel panel-flush rise" style={{ "--i": 1 }}>
      <div className="panel-header">
        <h2><IconInbox /> Inbox {unread > 0 && <span className="nav-count">{unread}</span>}</h2>
        <span className="muted small">from n8n automation</span>
      </div>
      {notifications.length === 0 && <p className="empty">No notifications yet.</p>}
      <ul className="inbox">
        {notifications.slice(0, 4).map((n) => (
          <li key={n.id} className={n.read ? "read" : ""}>
            <span className="inbox-dot" />
            <div>
              <strong>{n.title}</strong>
              <pre>{n.body}</pre>
              <div className="inbox-actions">
                <span className="muted">{relativeTime(n.created_at)}</span>
                {n.link && <a href={n.link}>Open</a>}
                {!n.read && (
                  <button className="link" onClick={() => markNotificationRead(n.id).then(onChange)}>
                    Mark as read
                  </button>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
