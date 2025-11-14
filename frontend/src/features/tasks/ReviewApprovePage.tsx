import { useMemo, useState } from 'react';
import { Alert, Box, Button, Paper, Stack } from '@mui/material';
import { useSnackbar } from 'notistack';
import {
  useApproveTasks,
  useRejectTasks,
  useReviewTasks,
  useUsers,
} from '../../api/hooks';
import { DataGridToolbar } from '../../components/DataGridToolbar';
import { TasksTable } from './TasksTable';
import { TaskDrawer } from '../../components/TaskDrawer';
import type { TaskStatus } from '../../types';

type StatusFilter = TaskStatus | 'all';

export const ReviewApprovePage = () => {
  const { data: tasks = [], isLoading, isError, refetch, isFetching } =
    useReviewTasks();
  const { data: users = [] } = useUsers();
  const approveTasks = useApproveTasks();
  const rejectTasks = useRejectTasks();
  const { enqueueSnackbar } = useSnackbar();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('draft');
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

  const handleBulkAction = async (
    ids: string[],
    mutate:
      | ReturnType<typeof useApproveTasks>
      | ReturnType<typeof useRejectTasks>,
    successMessage: string,
  ) => {
    if (!ids.length) return;
    try {
      await mutate.mutateAsync({ ids });
      enqueueSnackbar(successMessage, { variant: 'success' });
      setSelectedIds([]);
    } catch (error) {
      enqueueSnackbar((error as Error).message, { variant: 'error' });
    }
  };

  const disableSelectionActions =
    selectedIds.length === 0 ||
    approveTasks.isPending ||
    rejectTasks.isPending ||
    isLoading;

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
        Failed to load tasks. Please try again.
      </Alert>
    );
  }

  return (
    <Box>
      <DataGridToolbar
        title="Review & Approve"
        selectionCount={selectedIds.length}
        onApproveSelected={() =>
          handleBulkAction(selectedIds, approveTasks, 'Tasks approved')
        }
        onRejectSelected={() =>
          handleBulkAction(selectedIds, rejectTasks, 'Tasks rejected')
        }
        onApproveAll={() =>
          handleBulkAction(
            filteredTasks.map((task) => task.id),
            approveTasks,
            'All tasks approved',
          )
        }
        onRejectAll={() =>
          handleBulkAction(
            filteredTasks.map((task) => task.id),
            rejectTasks,
            'All tasks rejected',
          )
        }
        disableActions={disableSelectionActions}
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
      <TaskDrawer
        open={Boolean(drawerTaskId)}
        taskId={drawerTaskId}
        onClose={() => setDrawerTaskId(null)}
      />
      {(approveTasks.isPending || rejectTasks.isPending) && (
        <Stack direction="row" spacing={1} mt={2}>
          <Alert severity="info">Applying bulk changes…</Alert>
        </Stack>
      )}
    </Box>
  );
};
