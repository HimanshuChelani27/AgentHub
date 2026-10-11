import { Routes } from '@angular/router';

import { authGuard } from './core/auth';
import { Shell } from './layout/shell';

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./pages/login').then((m) => m.Login), title: 'Sign in · AgentHub' },
  {
    path: '',
    component: Shell,
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'overview' },
      { path: 'overview', loadComponent: () => import('./pages/overview').then((m) => m.Overview), title: 'Overview · AgentHub' },
      { path: 'playground', loadComponent: () => import('./pages/playground').then((m) => m.Playground), title: 'Playground · AgentHub' },
      { path: 'agents', loadComponent: () => import('./pages/agents').then((m) => m.Agents), title: 'Agents · AgentHub' },
      { path: 'servers', loadComponent: () => import('./pages/servers').then((m) => m.Servers), title: 'MCP servers · AgentHub' },
      { path: 'traces', loadComponent: () => import('./pages/traces').then((m) => m.Traces), title: 'Traces · AgentHub' },
      { path: 'traces/:id', loadComponent: () => import('./pages/trace-detail').then((m) => m.TraceDetail), title: 'Trace · AgentHub' },
      { path: 'audit', loadComponent: () => import('./pages/audit').then((m) => m.Audit), title: 'Audit log · AgentHub' },
      { path: 'policies', loadComponent: () => import('./pages/policies').then((m) => m.Policies), title: 'Policies · AgentHub' },
    ],
  },
  { path: '**', redirectTo: '' },
];
