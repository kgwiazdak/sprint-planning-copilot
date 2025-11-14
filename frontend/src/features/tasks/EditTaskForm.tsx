import {
  Autocomplete,
  Box,
  Button,
  Chip,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { Controller, useForm } from 'react-hook-form';
import { useEffect } from 'react';
import { useSnackbar } from 'notistack';
import { zodResolver } from '@hookform/resolvers/zod';
import {
  TaskUpdateSchema,
  issueTypeOptions,
  priorityOptions,
} from '../../schemas/task';
import type { TaskUpdateValues } from '../../schemas/task';
import { useUpdateTask, useUsers } from '../../api/hooks';
import type { Task } from '../../types';

type EditTaskFormProps = {
  task: Task;
  onSuccess?: (task: Task) => void;
  onCancel?: () => void;
  dense?: boolean;
};

export const EditTaskForm = ({
  task,
  onSuccess,
  onCancel,
  dense = false,
}: EditTaskFormProps) => {
  const { enqueueSnackbar } = useSnackbar();
  const { data: users } = useUsers();
  const updateTask = useUpdateTask();
  const {
    control,
    handleSubmit,
    reset,
    formState: { isValid, isDirty },
  } = useForm<TaskUpdateValues>({
    resolver: zodResolver(TaskUpdateSchema),
    mode: 'onChange',
    defaultValues: {
      summary: task.summary,
      description: task.description ?? '',
      issueType: task.issueType,
      priority: task.priority,
      storyPoints: task.storyPoints,
      assigneeId: task.assigneeId ?? '',
      labels: task.labels,
      status: task.status,
    },
  });

  useEffect(() => {
    reset({
      summary: task.summary,
      description: task.description ?? '',
      issueType: task.issueType,
      priority: task.priority,
      storyPoints: task.storyPoints,
      assigneeId: task.assigneeId ?? '',
      labels: task.labels,
      status: task.status,
    });
  }, [task, reset]);

  const onSubmit = handleSubmit(async (values) => {
    const payload = {
      ...values,
      assigneeId: values.assigneeId || undefined,
      storyPoints:
        values.storyPoints === undefined || Number.isNaN(values.storyPoints)
          ? undefined
          : values.storyPoints,
    };
    try {
      const updated = await updateTask.mutateAsync({
        id: task.id,
        data: payload,
      });
      enqueueSnackbar('Task updated', { variant: 'success' });
      onSuccess?.(updated);
    } catch (error) {
      enqueueSnackbar((error as Error).message, { variant: 'error' });
    }
  });

  return (
    <Box component="form" onSubmit={onSubmit}>
      <Stack spacing={dense ? 2 : 3}>
        <Controller
          name="summary"
          control={control}
          render={({ field, fieldState }) => (
            <TextField
              {...field}
              label="Summary"
              required
              error={Boolean(fieldState.error)}
              helperText={fieldState.error?.message}
            />
          )}
        />
        <Controller
          name="description"
          control={control}
          render={({ field, fieldState }) => (
            <TextField
              {...field}
              label="Description"
              multiline
              minRows={3}
              error={Boolean(fieldState.error)}
              helperText={fieldState.error?.message}
            />
          )}
        />
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <Controller
            name="issueType"
            control={control}
            render={({ field, fieldState }) => (
              <TextField
                {...field}
                select
                label="Issue type"
                fullWidth
                error={Boolean(fieldState.error)}
                helperText={fieldState.error?.message}
              >
                {issueTypeOptions.map((option) => (
                  <MenuItem key={option} value={option}>
                    {option}
                  </MenuItem>
                ))}
              </TextField>
            )}
          />
          <Controller
            name="priority"
            control={control}
            render={({ field, fieldState }) => (
              <TextField
                {...field}
                select
                label="Priority"
                fullWidth
                error={Boolean(fieldState.error)}
                helperText={fieldState.error?.message}
              >
                {priorityOptions.map((option) => (
                  <MenuItem key={option} value={option}>
                    {option}
                  </MenuItem>
                ))}
              </TextField>
            )}
          />
        </Stack>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <Controller
            name="storyPoints"
            control={control}
            render={({ field, fieldState }) => (
              <TextField
                {...field}
                type="number"
                label="Story points"
                fullWidth
                value={field.value ?? ''}
                onChange={(event) => {
                  const value = event.target.value;
                  field.onChange(value === '' ? undefined : Number(value));
                }}
                error={Boolean(fieldState.error)}
                helperText={fieldState.error?.message}
              />
            )}
          />
          <Controller
            name="assigneeId"
            control={control}
            render={({ field }) => (
              <TextField {...field} select label="Assignee" fullWidth>
                <MenuItem value="">Unassigned</MenuItem>
                {users?.map((user) => (
                  <MenuItem key={user.id} value={user.id}>
                    {user.displayName}
                  </MenuItem>
                ))}
              </TextField>
            )}
          />
        </Stack>
        <Controller
          name="labels"
          control={control}
          render={({ field, fieldState }) => (
            <Autocomplete
              multiple
              freeSolo
              options={[]}
              value={field.value}
              onChange={(_event, value) => field.onChange(value)}
              renderTags={(value, getTagProps) =>
                value.map((option, index) => (
                  <Chip
                    {...getTagProps({ index })}
                    key={option}
                    label={option}
                  />
                ))
              }
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Labels"
                  error={Boolean(fieldState.error)}
                  helperText={fieldState.error?.message}
                />
              )}
            />
          )}
        />
        {task.sourceQuote && (
          <Box
            p={2}
            borderRadius={2}
            bgcolor="background.paper"
            border={1}
            borderColor="divider"
          >
            <Typography variant="body2" color="text.secondary">
              Source quote
            </Typography>
            <Typography variant="body2">{task.sourceQuote}</Typography>
          </Box>
        )}
        <Stack direction="row" justifyContent="flex-end" spacing={2}>
          {onCancel && (
            <Button variant="text" onClick={onCancel}>
              Cancel
            </Button>
          )}
          <Button
            type="submit"
            disabled={!isValid || updateTask.isPending || !isDirty}
          >
            Save
          </Button>
        </Stack>
      </Stack>
    </Box>
  );
};
