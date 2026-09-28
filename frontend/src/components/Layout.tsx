import { NavLink, Outlet } from 'react-router-dom';
import {
  IconAbout,
  IconApiDocs,
  IconDashboard,
  IconEnvironments,
  IconJourneys,
  IconPersonas,
} from './NavIcons';

const mainNavItems: {
  to: string;
  label: string;
  icon: typeof IconDashboard;
  wip?: boolean;
}[] = [
  { to: '/', label: 'Dashboard', icon: IconDashboard },
  { to: '/personas', label: 'Personas', icon: IconPersonas },
  { to: '/journeys', label: 'Journeys', icon: IconJourneys },
  { to: '/environments', label: 'Environments', icon: IconEnvironments, wip: true },
];

const resourceNavItems = [
  { to: '/about', label: 'About', icon: IconAbout },
  { to: '/api-docs', label: 'API Docs', icon: IconApiDocs },
];

export default function Layout() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1 className="sidebar-title">SimCrew</h1>
        </div>
        <nav className="sidebar-nav">
          {mainNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  `nav-link${isActive ? ' nav-link--active' : ''}`
                }
              >
                <Icon className="nav-link__icon" />
                <span>{item.label}</span>
                {item.wip && <span className="nav-link__wip">WIP</span>}
              </NavLink>
            );
          })}
          <div className="sidebar-section">
            <span className="sidebar-section__label">Resources</span>
            {resourceNavItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `nav-link${isActive ? ' nav-link--active' : ''}`
                  }
                >
                  <Icon className="nav-link__icon" />
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </div>
        </nav>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
