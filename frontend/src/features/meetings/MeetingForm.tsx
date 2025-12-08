import {useEffect, useMemo, useState} from 'react';
import {Button, FormHelperText, MenuItem, Stack, TextField, Typography} from '@mui/material';
import {Controller, useForm} from 'react-hook-form';
import {zodResolver} from '@hookform/resolvers/zod';
import type {MeetingFormValues} from '../../schemas/meeting';
import {MeetingSchema} from '../../schemas/meeting';
import {useSnackbar} from 'notistack';
import {apiClient} from '../../api/client';
import {useJiraProjects} from '../../api/hooks';

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
    const {enqueueSnackbar} = useSnackbar();
    const [mockLoading, setMockLoading] = useState(false);
    const isDevProfile =
        (import.meta.env.VITE_APP_PROFILE || '').toLowerCase() === 'dev';
    const {
        data: projects = [],
        isLoading: projectsLoading,
        isError: projectsError,
    } = useJiraProjects();
    const projectOptions = useMemo(
        () =>
            projects.map((project) => ({
                value: project.key,
                label: `${project.name} (${project.key})`,
            })),
        [projects],
    );
    const {
        control,
        handleSubmit,
        formState: {isValid},
        watch,
        setValue,
    } = useForm<MeetingFormValues>({
        resolver: zodResolver(MeetingSchema),
        mode: 'onChange',
        defaultValues: {
            title: '',
            startedAt: new Date().toISOString().slice(0, 16),
            projectKey: defaultValues?.projectKey ?? '',
            ...defaultValues,
        },
    });

    const projectKeyValue = watch('projectKey');
    useEffect(() => {
        if (!projectKeyValue && projectOptions.length) {
            setValue('projectKey', projectOptions[0].value, {shouldValidate: true});
        }
    }, [projectKeyValue, projectOptions, setValue]);

    return (
        <Stack
            component="form"
            spacing={3}
            encType="multipart/form-data"
            onSubmit={handleSubmit((values) => onSubmit(values))}
        >
            <Controller
                name="title"
                control={control}
                render={({field, fieldState}) => (
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
                render={({field, fieldState}) => (
                    <TextField
                        {...field}
                        label="Date & time"
                        type="datetime-local"
                        InputLabelProps={{shrink: true}}
                        error={Boolean(fieldState.error)}
                        helperText={fieldState.error?.message}
                    />
                )}
            />
            <Controller
                name="projectKey"
                control={control}
                render={({field, fieldState}) => (
                    <TextField
                        {...field}
                        select
                        label="Jira project"
                        required
                        disabled={projectsLoading || projectOptions.length === 0}
                        error={Boolean(fieldState.error) || projectsError}
                        helperText={
                            fieldState.error?.message ||
                            (projectsError ? 'Failed to load Jira projects' : undefined)
                        }
                    >
                        {projectOptions.map((option) => (
                            <MenuItem key={option.value} value={option.value}>
                                {option.label}
                            </MenuItem>
                        ))}
                    </TextField>
                )}
            />
            <Controller
                name="file"
                control={control}
                render={({field: {onChange, value, ref}, fieldState}) => {
                    const handleMockSelect = async () => {
                        setMockLoading(true);
                        try {
                            const response = await apiClient.get('/mock/audio', {
                                responseType: 'blob',
                            });
                            const blob: Blob = response.data;
                            const disposition = response.headers['content-disposition'] || '';
                            const match = disposition.match(/filename="?([^";]+)"?/i);
                            const filename = match?.[1] || 'mock_meeting.mp3';
                            const contentType =
                                blob.type || response.headers['content-type'] || 'audio/mpeg';
                            const mockFile = new File([blob], filename, {type: contentType});
                            onChange(mockFile);
                            enqueueSnackbar('Mock audio attached', {variant: 'info'});
                        } catch (error) {
                            enqueueSnackbar((error as Error).message, {variant: 'error'});
                        } finally {
                            setMockLoading(false);
                        }
                    };

                    return (
                        <Stack spacing={1}>
                            <Stack direction="row" spacing={1}>
                                <Button variant="outlined" component="label" sx={{flex: 1}}>
                                    {value?.name ? 'Change audio file' : 'Upload audio file'}
                                    <input
                                        type="file"
                                        hidden
                                        ref={ref}
                                        accept="audio/*,.mp3,.wav,.m4a,.aac,.wma,.ogg,.txt,.json"
                                        onChange={(event) => {
                                            const file = event.target.files?.[0];
                                            onChange(file);
                                            event.target.value = '';
                                        }}
                                    />
                                </Button>
                                {isDevProfile && (
                                    <Button
                                        variant="outlined"
                                        onClick={handleMockSelect}
                                        disabled={mockLoading}
                                        sx={{flex: 1}}
                                    >
                                        {mockLoading ? 'Loading mock…' : 'Select mock file'}
                                    </Button>
                                )}
                            </Stack>
                            <Typography variant="body2" color="text.secondary">
                                {value?.name ?? 'No file selected'}
                            </Typography>
                            {fieldState.error && (
                                <FormHelperText error>{fieldState.error.message}</FormHelperText>
                            )}
                        </Stack>
                    );
                }}
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
