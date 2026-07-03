import React from "react";
import { UserRound } from "lucide-react";

const serviceUsers = [
  { id: "zhangsan", name: "张三", age: 65, profile: "高血压", note: "今日有计划", status: "重点关注" },
  { id: "lisi", name: "李四", age: 72, profile: "糖尿病", note: "随访对象", status: "随访" },
  { id: "wangwu", name: "王五", age: 58, profile: "长期胃病", note: "近期有问询", status: "观察" }
];

export function ServiceUserList() {
  return (
    <section className="records-panel service-users-panel">
      <div className="records-panel-heading">
        <p>固定服务对象</p>
        <h2>服务对象</h2>
      </div>
      <div className="service-user-list">
        {serviceUsers.map((user) => (
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
      </div>
    </section>
  );
}
