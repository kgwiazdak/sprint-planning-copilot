import {Box, Button, List, ListItem, ListItemIcon, ListItemText, Paper, Stack, Typography,} from '@mui/material';
import {CheckCircleOutline} from '@mui/icons-material';
import {useNavigate} from 'react-router-dom';
import {useSnackbar} from 'notistack';
import {MeetingForm} from './MeetingForm';
import {useCreateMeeting} from '../../api/hooks';
import type {MeetingFormValues} from '../../schemas/meeting';
import {PageHeader} from '../../components/PageHeader';

export const NewMeetingForm = () => {
    const createMeeting = useCreateMeeting();
    const {enqueueSnackbar} = useSnackbar();
    const navigate = useNavigate();

    const handleSubmit = async (values: MeetingFormValues) => {
        const file = values.file;
        if (!file) {
            enqueueSnackbar('Audio file is required', {variant: 'error'});
            return;
        }
        try {
            await createMeeting.mutateAsync({
                title: values.title,
                startedAt: new Date(values.startedAt).toISOString(),
                file,
            });
            enqueueSnackbar('Meeting created', {variant: 'success'});
            navigate('/meetings');
        } catch (error) {
            enqueueSnackbar((error as Error).message, {variant: 'error'});
        }
    };

    return (
        <Box>
            <PageHeader
                eyebrow="Import wizard"
                title="New meeting"
                subtitle="Provide metadata and attach the recorded meeting or transcript; the worker handles transcription, LLM extraction, and MLflow logging."
                actions={
                    <Button variant="text" onClick={() => navigate('/meetings')}>
                        Back to log
                    </Button>
                }
            />
            <Stack
                direction={{xs: 'column', lg: 'row'}}
                spacing={3}
                alignItems="stretch"
            >
                <Paper sx={{p: {xs: 3, md: 4}, flex: {lg: '0.6'}}}>
                    <MeetingForm
                        onSubmit={handleSubmit}
                        loading={createMeeting.isPending}
                        submitLabel="Start import"
                        onCancel={() => navigate(-1)}
                    />
                </Paper>
                <Paper sx={{p: {xs: 3, md: 4}, flex: 1}}>
                    <Typography variant="h6" mb={1}>
                        Upload tips
                    </Typography>
                    <Typography variant="body2" color="text.secondary" mb={2}>
                        Files go straight to blob storage via SAS, so there is no size limit on the API call.
                    </Typography>
                    <List dense>
                        {[
                            'Audio or transcript formats are accepted (.mp3, .wav, .m4a, .txt, .json).',
                            'Started at timestamps help align diarization across speakers.',
                            'Enable MOCK_LLM=1 locally to get deterministic task extraction while testing.',
                        ].map((tip) => (
                            <ListItem key={tip} disableGutters sx={{alignItems: 'flex-start'}}>
                                <ListItemIcon sx={{minWidth: 36, mt: 0.4}}>
                                    <CheckCircleOutline color="primary" fontSize="small"/>
                                </ListItemIcon>
                                <ListItemText
                                    primary={
                                        <Typography variant="body2" color="text.secondary">
                                            {tip}
                                        </Typography>
                                    }
                                />
                            </ListItem>
                        ))}
                    </List>
                </Paper>
            </Stack>
        </Box>
    );
};
