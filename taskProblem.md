Based on an analysis of both the frontend (`clientadmin`) and the backend (`server`), here are the exact points where the **Task page** (`/tasks`) can break or fail to show/render:

---

### 1. Route Access Guard & Missing Permission (Most Likely)
In [App.jsx](file:///D:/Fillip/Fbos_frontend/clientadmin/src/app/App.jsx#L193):
```jsx
<Route path="/tasks" element={<RequireAccess rule={ACCESS.tasks}><Tasks /></RequireAccess>} />
```
And in [navigation.jsx](file:///D:/Fillip/Fbos_frontend/clientadmin/src/app/navigation.jsx#L80-L84):
```javascript
{ to: '/tasks', label: 'Tasks', access: ACCESS.tasks }
```
Where [access.js](file:///D:/Fillip/Fbos_frontend/clientadmin/src/features/auth/access.js#L125) defines:
```javascript
tasks: { permissions: ['delivery.task.read'] }
```
* **The Break Point**: If the signed-in user is not a `client_admin` and lacks the `'delivery.task.read'` permission code in Identity:
  * The **"Tasks"** link is completely hidden from the sidebar navigation.
  * Navigating directly to `/tasks` renders the access-denied block from [`RequireAccess.jsx`](file:///D:/Fillip/Fbos_frontend/clientadmin/src/features/auth/components/RequireAccess.jsx#L9-L13) (*"You don't have access to this page"*), preventing the `Tasks` component from mounting at all.

---

### 2. Microservice Proxy / Port Mismatch (`DELIVERY_URL`)
Delivery is an independent microservice (`03_delivery`) running on **port 8003** (not Identity's 8001 or Revenue's 8002).

In [vite.config.js](file:///D:/Fillip/Fbos_frontend/clientadmin/vite.config.js#L16-L56):
```javascript
const DELIVERY_URL = process.env.DELIVERY_URL || process.env.API_URL || 'http://localhost:8003'
...
'/api/delivery': {
  target: DELIVERY_URL,
  changeOrigin: true,
}
```
* **The Break Point**: 
  * If the delivery container (`server-delivery-1`) is stopped, not healthy, or port 8003 is not mapped.
  * Or if the frontend was launched pointing `API_URL` directly to Identity (`http://localhost:8001`) instead of the Gateway (`http://localhost:8000`), `/api/delivery/v1/*` requests return `404 Not Found` or `ECONNREFUSED`.
  * Because [`useTaskTypes`](file:///D:/Fillip/Fbos_frontend/clientadmin/src/features/delivery/useTaskTypes.js#L9) and [`tasksApi.list`](file:///D:/Fillip/Fbos_frontend/clientadmin/src/features/delivery/api.js#L68) call `/api/delivery/v1/task-types` and `/api/delivery/v1/tasks`, both fail on page load.

---

### 3. Missing `orgId` / Organization Not Settled
In [Tasks.jsx](file:///D:/Fillip/Fbos_frontend/clientadmin/src/features/delivery/pages/Tasks.jsx#L33):
```javascript
const { orgId, activeOrg } = useActiveOrg()
```
And in `TaskList` & `TeamQueue`:
```javascript
{ enabled: Boolean(orgId) }
```
* **The Break Point**: If `orgId` is `undefined` (for example, before [`ActiveOrgProvider`](file:///D:/Fillip/Fbos_frontend/clientadmin/src/features/organizations/ActiveOrg.jsx#L52) finishes loading or if the user has no active organization selected), all queries are disabled. The component will render empty panels or skeletons and will never fetch tasks or task types.

---

### 4. Uncaught Runtime Errors During Rendering
Unlike API errors that show an [`ErrorBanner`](file:///D:/Fillip/Fbos_frontend/clientadmin/src/shared/components/ErrorBanner.jsx), an unhandled JavaScript exception in a React render loop crashes the whole component tree (white screen of death):

1. **Missing `task_type` in [`TaskTable.jsx`](file:///D:/Fillip/Fbos_frontend/clientadmin/src/features/delivery/components/TaskTable.jsx#L39)**:
   ```jsx
   <span className={`discipline-dot ${t.task_type.discipline}`} /> · {t.task_type.name}
   ```
   If any task returned from the API has `task_type` as `null` or `undefined`, accessing `.discipline` crashes with:
   `TypeError: Cannot read properties of undefined (reading 'discipline')`.

2. **Missing `stage` in `governing_workflow` in [`TaskTable.jsx`](file:///D:/Fillip/Fbos_frontend/clientadmin/src/features/delivery/components/TaskTable.jsx#L48)**:
   ```jsx
   {t.governing_workflow && <div className="muted small">{t.governing_workflow.stage.name}</div>}
   ```
   If `governing_workflow` is present but `stage` is null, accessing `.name` causes an immediate crash.

3. **Missing `attributes` on Blocked Tasks in [`TaskDetail.jsx`](file:///D:/Fillip/Fbos_frontend/clientadmin/src/features/delivery/pages/TaskDetail.jsx#L136-L137)** *(if on the task detail page `/tasks/:id`)*:
   ```jsx
   {task.status === 'blocked' && task.attributes.blocked_reason && (
   ```
   Notice that unlike line 75 (`task.attributes?.story_points`), line 136 does not use optional chaining (`?.`). If `attributes` is `null` on a blocked task, it crashes with `TypeError: Cannot read properties of null (reading 'blocked_reason')`.

4. **Undefined `taskTypes` in [`TaskFilterBar.jsx`](file:///D:/Fillip/Fbos_frontend/clientadmin/src/features/delivery/components/TaskFilterBar.jsx#L11)**:
   ```javascript
   const disciplines = [...new Set([...DISCIPLINE_ORDER, ...taskTypes.map((t) => t.discipline)])]
   ```
   If `taskTypes` is passed as `undefined` (or not yet initialized as an array), `.map()` will throw `TypeError: Cannot read properties of undefined (reading 'map')`.

---

### 5. Console Port Mismatch (`superadmin` vs `clientadmin`)
* **Port 5173 (`superadmin`)**: Only serves `/clients`. It does not contain any delivery or task pages. If you type `/tasks` on `localhost:5173`, the catch-all route redirects you to `/clients`.
* **Port 5174 (`clientadmin`)**: Contains the full Tasks workspace (`/tasks`, `/tasks/:id`, `/tasks/new`, `/task-types`).