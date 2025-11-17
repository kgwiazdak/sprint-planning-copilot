import {
  AddCircleOutline,
  CalendarMonth,
  FactCheck,
  GraphicEq,
  ListAlt,
} from '@mui/icons-material';
import {
  Box,
  Chip,
  Divider,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Paper,
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
import { VoiceProfilesPage } from '../features/users/VoiceProfilesPage';

const baseNavItems = [
  { label: 'Review & Approve', path: '/review', icon: <FactCheck /> },
  { label: 'Meetings', path: '/meetings', icon: <CalendarMonth /> },
  { label: 'New Meeting', path: '/meetings/new', icon: <AddCircleOutline /> },
  { label: 'Voice Profiles', path: '/voices', icon: <GraphicEq /> },
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
        baseNavItems[3],
      ]
    : baseNavItems;

  return (
    <List sx={{ flexGrow: 1, mt: 1 }}>
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
              mb: 0.5,
              gap: 1.5,
              px: 1.5,
              py: 1.2,
            }}
          >
            <ListItemIcon
              sx={{
                minWidth: 32,
                color: 'inherit',
              }}
            >
              {item.icon}
            </ListItemIcon>
            <ListItemText
              primaryTypographyProps={{
                fontWeight: 600,
                fontSize: 14,
              }}
            >
              {item.label}
            </ListItemText>
          </ListItemButton>
        );
      })}
    </List>
  );
};

export const App = () => (
  <Box
    sx={(theme) => ({
      minHeight: '100vh',
      backgroundColor: theme.palette.background.default,
      backgroundImage:
        theme.palette.mode === 'light'
          ? 'radial-gradient(circle at 20% 20%, rgba(14,165,233,0.2), transparent 45%), radial-gradient(circle at 80% 0%, rgba(99,102,241,0.12), transparent 40%)'
          : 'radial-gradient(circle at 20% 20%, rgba(2,132,199,0.35), transparent 45%), radial-gradient(circle at 80% 0%, rgba(99,102,241,0.2), transparent 40%)',
    })}
  >
    <Box
      sx={{
        maxWidth: '1500px',
        margin: '0 auto',
        display: 'flex',
        flexDirection: { xs: 'column', md: 'row' },
        gap: { xs: 3, md: 4 },
        padding: { xs: 3, md: 5 },
      }}
    >
      <Paper
        component="nav"
        elevation={0}
        sx={(theme) => ({
          width: { xs: '100%', md: drawerWidth },
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: 3,
          px: { xs: 3, md: 3 },
          py: { xs: 3, md: 4 },
          borderRadius: 3,
          position: 'sticky',
          top: { xs: 16, md: 32 },
          alignSelf: { xs: 'stretch', md: 'flex-start' },
          background:
            theme.palette.mode === 'light'
              ? 'rgba(255,255,255,0.9)'
              : 'rgba(15,23,42,0.92)',
        })}
      >
        <Stack spacing={1}>
          <Chip
            label="Sprint planning copilot"
            color="primary"
            size="small"
            sx={{ alignSelf: 'flex-start' }}
          />
          <Typography variant="h5" fontWeight={700}>
            AI Scrum Co-Pilot
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Upload meetings, let extraction run in the background, and keep humans in the loop for approvals.
          </Typography>
        </Stack>
        <Box
          sx={(theme) => ({
            borderRadius: 2,
            p: 2.5,
            background:
              theme.palette.mode === 'light'
                ? 'linear-gradient(135deg, rgba(37,99,235,0.12), rgba(14,165,233,0.12))'
                : 'linear-gradient(135deg, rgba(99,102,241,0.25), rgba(14,165,233,0.2))',
          })}
        >
          <Typography
            variant="subtitle2"
            color="primary"
            fontWeight={600}
            gutterBottom
          >
            Workflow at a glance
          </Typography>
          <Typography variant="body2" color="text.secondary">
            1) Upload or import meetings. 2) Let the worker transcribe & extract tasks. 3) Approve Jira-ready issues.
          </Typography>
        </Box>
        <NavList />
        <Divider />
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Box>
            <Typography variant="subtitle2" fontWeight={600}>
              Theme
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Toggle layout mood
            </Typography>
          </Box>
          <ThemeToggleButton />
        </Stack>
      </Paper>
      <Box
        component="main"
        flexGrow={1}
        sx={(theme) => ({
          borderRadius: 4,
          border: `1px solid ${theme.palette.divider}`,
          padding: { xs: 2.5, md: 4 },
          backdropFilter: 'blur(12px)',
          backgroundColor:
            theme.palette.mode === 'light'
              ? 'rgba(255,255,255,0.92)'
              : 'rgba(2,6,23,0.8)',
          boxShadow:
            theme.palette.mode === 'light'
              ? '0 35px 65px rgba(15,23,42,0.15)'
              : '0 40px 70px rgba(2,6,23,0.85)',
          minHeight: { md: 'calc(100vh - 96px)' },
        })}
      >
        <Routes>
          <Route path="/" element={<Navigate to="/review" replace />} />
          <Route path="/review" element={<ReviewApprovePage />} />
          <Route path="/meetings" element={<MeetingsList />} />
          <Route path="/meetings/new" element={<NewMeetingForm />} />
          <Route path="/meetings/:id/tasks" element={<MeetingTasksPage />} />
          <Route path="/tasks/:id/edit" element={<EditTaskPage />} />
          <Route path="/voices" element={<VoiceProfilesPage />} />
          <Route path="*" element={<Navigate to="/review" replace />} />
        </Routes>
      </Box>
    </Box>
  </Box>
);
