import React from "react";
import { UserRound } from "lucide-react";

export function ServiceUserList({ users = [] }) {
  return (
    <section className="records-panel service-users-panel">
      <div className="records-panel-heading">
        <p>服务对象</p>
        <h2>服务对象</h2>
      </div>
      <div className="service-user-list">
        {users.map((user) => (
          <article key={user.id} className="service-user-card">
            <span className="service-user-icon" aria-hidden="true">
              <UserRound size={24} />
            </span>
            <div>
              <strong>{user.name}</strong>
              <p>
                {user.age}岁 · {user.profile}
              </p>
              <small>{user.note}</small>
            </div>
            <em>{user.status}</em>
          </article>
        ))}
        {users.length === 0 && <p className="empty-list-note">暂无服务对象记录</p>}
      </div>
    </section>
  );
}
