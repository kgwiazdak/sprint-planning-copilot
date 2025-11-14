import {
  AddCircleOutline,
  CalendarMonth,
  FactCheck,
  ListAlt,
} from '@mui/icons-material';
import {
  Box,
  Divider,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Typography,
} from '@mui/material';
import {
  Link as RouterLink,
  Navigate,
  Route,
  Routes,
  matchPath,
  useLocation,
} from 'react-router-dom';
import { ThemeToggleButton } from './theme';
import { drawerWidth } from '../utils/constants';
import { ReviewApprovePage } from '../features/tasks/ReviewApprovePage';
import { MeetingsList } from '../features/meetings/MeetingsList';
import { NewMeetingForm } from '../features/meetings/NewMeetingForm';
import { MeetingTasksPage } from '../features/tasks/MeetingTasksPage';
import { EditTaskPage } from '../features/tasks/EditTaskPage';

const baseNavItems = [
  { label: 'Review & Approve', path: '/review', icon: <FactCheck /> },
  { label: 'Meetings', path: '/meetings', icon: <CalendarMonth /> },
  { label: 'New Meeting', path: '/meetings/new', icon: <AddCircleOutline /> },
];

const NavList = () => {
  const location = useLocation();
  const tasksMatch = matchPath('/meetings/:id/tasks', location.pathname);
  const navItems = tasksMatch
    ? [
        baseNavItems[0],
        baseNavItems[1],
        {
          label: 'Meeting Tasks',
          path: location.pathname,
          icon: <ListAlt />,
        },
        baseNavItems[2],
      ]
    : baseNavItems;

  return (
    <List sx={{ flexGrow: 1 }}>
      {navItems.map((item) => {
        const isActive =
          location.pathname === item.path ||
          location.pathname.startsWith(`${item.path}/`);
        return (
          <ListItemButton
            key={item.path}
            component={RouterLink}
            to={item.path}
            selected={isActive}
            sx={{
              borderRadius: 1,
              mb: 0.5,
            }}
          >
            <ListItemIcon sx={{ minWidth: 32 }}>{item.icon}</ListItemIcon>
            <ListItemText primaryTypographyProps={{ fontWeight: 500 }}>
              {item.label}
            </ListItemText>
          </ListItemButton>
        );
      })}
    </List>
  );
};

export const App = () => (
  <Box display="flex" minHeight="100vh" bgcolor="background.default">
    <Box
      component="nav"
      width={drawerWidth}
      bgcolor="background.paper"
      borderRight={1}
      borderColor="divider"
      p={3}
      display="flex"
      flexDirection="column"
    >
      <Typography variant="h6" fontWeight={700}>
        AI Scrum Co-Pilot
      </Typography>
      <Typography variant="body2" color="text.secondary" mb={3}>
        Human-in-the-loop review
      </Typography>
      <NavList />
      <Divider sx={{ my: 2 }} />
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Typography variant="body2" fontWeight={500}>
          Theme
        </Typography>
        <ThemeToggleButton />
      </Stack>
    </Box>
    <Box component="main" flexGrow={1} p={4}>
      <Routes>
        <Route path="/" element={<Navigate to="/review" replace />} />
        <Route path="/review" element={<ReviewApprovePage />} />
        <Route path="/meetings" element={<MeetingsList />} />
        <Route path="/meetings/new" element={<NewMeetingForm />} />
        <Route path="/meetings/:id/tasks" element={<MeetingTasksPage />} />
        <Route path="/tasks/:id/edit" element={<EditTaskPage />} />
        <Route path="*" element={<Navigate to="/review" replace />} />
      </Routes>
    </Box>
  </Box>
);
