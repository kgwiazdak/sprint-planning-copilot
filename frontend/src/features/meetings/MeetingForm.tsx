import { Button, Stack, TextField } from '@mui/material';
import { Controller, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import type { MeetingFormValues } from '../../schemas/meeting';
import { MeetingSchema } from '../../schemas/meeting';

type MeetingFormProps = {
  defaultValues?: Partial<MeetingFormValues>;
  submitLabel?: string;
  onSubmit: (values: MeetingFormValues) => Promise<void> | void;
  loading?: boolean;
  onCancel?: () => void;
};

export const MeetingForm = ({
  defaultValues,
  submitLabel = 'Save',
  onSubmit,
  loading,
  onCancel,
}: MeetingFormProps) => {
  const {
    control,
    handleSubmit,
    formState: { isValid },
  } = useForm<MeetingFormValues>({
    resolver: zodResolver(MeetingSchema),
    mode: 'onChange',
    defaultValues: {
      title: '',
      startedAt: new Date().toISOString().slice(0, 16),
      sourceUrl: '',
      sourceText: '',
      ...defaultValues,
    },
  });

  return (
    <Stack
      component="form"
      spacing={3}
      onSubmit={handleSubmit((values) => onSubmit(values))}
    >
      <Controller
        name="title"
        control={control}
        render={({ field, fieldState }) => (
          <TextField
            {...field}
            label="Meeting title"
            required
            error={Boolean(fieldState.error)}
            helperText={fieldState.error?.message}
          />
        )}
      />
      <Controller
        name="startedAt"
        control={control}
        render={({ field, fieldState }) => (
          <TextField
            {...field}
            label="Date & time"
            type="datetime-local"
            InputLabelProps={{ shrink: true }}
            error={Boolean(fieldState.error)}
            helperText={fieldState.error?.message}
          />
        )}
      />
      <Controller
        name="sourceUrl"
        control={control}
        render={({ field, fieldState }) => (
          <TextField
            {...field}
            label="Transcript URL"
            placeholder="https://"
            error={Boolean(fieldState.error)}
            helperText={fieldState.error?.message ?? 'Link to transcript or recording'}
          />
        )}
      />
      <Controller
        name="sourceText"
        control={control}
        render={({ field, fieldState }) => (
          <TextField
            {...field}
            label="Transcript text"
            multiline
            minRows={4}
            error={Boolean(fieldState.error)}
            helperText={fieldState.error?.message}
          />
        )}
      />
      <Stack direction="row" justifyContent="flex-end" spacing={2}>
        {onCancel && (
          <Button variant="text" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={!isValid || loading}>
          {submitLabel}
        </Button>
      </Stack>
    </Stack>
  );
};
