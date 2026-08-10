import React from "react";
import { UserRound } from "lucide-react";

export function ServiceUserList({ users = [], onSelectUser }) {
  return (
    <section className="records-panel service-users-panel">
      <div className="records-panel-heading">
        <h2>服务对象</h2>
      </div>
      <div className="service-user-list">
        {users.map((user) => (
          <button
            key={user.id}
            type="button"
            className="service-user-card"
            aria-label={`查看${user.name}的历史问询`}
            onClick={(event) => onSelectUser?.(user, event.currentTarget)}
          >
            <div className="service-user-card-header">
              <span className="service-user-icon" aria-hidden="true">
                <UserRound size={24} />
              </span>
              <div className="service-user-heading">
                <strong>{user.name}</strong>
                <em>{user.status}</em>
              </div>
            </div>
            <p>{user.age}岁 · {user.profile}</p>
            <small>{user.note}</small>
          </button>
        ))}
        {users.length === 0 && <p className="empty-list-note">暂无服务对象记录</p>}
      </div>
    </section>
  );
}
