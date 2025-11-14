import { useMemo, useState } from 'react';
import { Alert, Box, Button, Paper, Stack } from '@mui/material';
import { useNavigate, useParams } from 'react-router-dom';
import { useSnackbar } from 'notistack';
import {
  useApproveTasks,
  useMeeting,
  useMeetingTasks,
  useRejectTasks,
  useUsers,
} from '../../api/hooks';
import { TasksTable } from './TasksTable';
import { DataGridToolbar } from '../../components/DataGridToolbar';
import { TaskDrawer } from '../../components/TaskDrawer';
import type { TaskStatus } from '../../types';

type StatusFilter = TaskStatus | 'all';

export const MeetingTasksPage = () => {
  const { id = '' } = useParams();
  const { data: meeting } = useMeeting(id);
  const {
    data: tasks = [],
    isLoading,
    isError,
    refetch,
    isFetching,
  } = useMeetingTasks(id);
  const { data: users = [] } = useUsers();
  const approveTasks = useApproveTasks();
  const rejectTasks = useRejectTasks();
  const navigate = useNavigate();
  const { enqueueSnackbar } = useSnackbar();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [search, setSearch] = useState('');
  const [drawerTaskId, setDrawerTaskId] = useState<string | null>(null);

  const filteredTasks = useMemo(
    () =>
      tasks
        .filter((task) =>
          statusFilter === 'all' ? true : task.status === statusFilter,
        )
        .filter((task) =>
          task.summary.toLowerCase().includes(search.toLowerCase()),
        ),
    [tasks, statusFilter, search],
  );

  if (!id) {
    return <Alert severity="warning">Meeting not found.</Alert>;
  }

  const disableBulk =
    selectedIds.length === 0 ||
    approveTasks.isPending ||
    rejectTasks.isPending ||
    isLoading;

  const handleBulkAction = async (
    ids: string[],
    mutation:
      | ReturnType<typeof useApproveTasks>
      | ReturnType<typeof useRejectTasks>,
    message: string,
  ) => {
    if (!ids.length) return;
    try {
      await mutation.mutateAsync({ ids });
      enqueueSnackbar(message, { variant: 'success' });
      setSelectedIds([]);
    } catch (error) {
      enqueueSnackbar((error as Error).message, { variant: 'error' });
    }
  };

  if (isError) {
    return (
      <Alert
        severity="error"
        action={
          <Button color="inherit" size="small" onClick={() => refetch()}>
            Retry
          </Button>
        }
      >
        Failed to load meeting tasks.
      </Alert>
    );
  }

  return (
    <Box>
      <DataGridToolbar
        title={meeting ? `${meeting.title} tasks` : 'Meeting tasks'}
        selectionCount={selectedIds.length}
        onApproveSelected={() =>
          handleBulkAction(selectedIds, approveTasks, 'Tasks approved')
        }
        onRejectSelected={() =>
          handleBulkAction(selectedIds, rejectTasks, 'Tasks rejected')
        }
        disableActions={disableBulk}
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        search={search}
        onSearchChange={setSearch}
      />
      <Paper sx={{ p: 2 }}>
        <TasksTable
          tasks={filteredTasks}
          users={users}
          loading={isLoading || isFetching}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          onRowDoubleClick={(task) => setDrawerTaskId(task.id)}
        />
      </Paper>
      <Stack direction="row" spacing={2} mt={2}>
        <Button
          variant="outlined"
          disabled={selectedIds.length !== 1}
          onClick={() =>
            selectedIds.length === 1 && navigate(`/tasks/${selectedIds[0]}/edit`)
          }
        >
          Edit task
        </Button>
        <Button variant="text" onClick={() => navigate('/meetings')}>
          Back to meetings
        </Button>
      </Stack>
      <TaskDrawer
        open={Boolean(drawerTaskId)}
        taskId={drawerTaskId}
        onClose={() => setDrawerTaskId(null)}
      />
    </Box>
  );
};
