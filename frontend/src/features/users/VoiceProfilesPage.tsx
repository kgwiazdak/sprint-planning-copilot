import { useEffect, useMemo, useState } from 'react';
import {
  Autocomplete,
  Box,
  Button,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { useSnackbar } from 'notistack';
import { useUploadVoiceSample, useUsers } from '../../api/hooks';
import type { User } from '../../types';
import { PageHeader } from '../../components/PageHeader';

export const VoiceProfilesPage = () => {
  const { data: users = [], isLoading } = useUsers();
  const uploadVoice = useUploadVoiceSample();
  const { enqueueSnackbar } = useSnackbar();
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [displayName, setDisplayName] = useState('');
  const [file, setFile] = useState<File | null>(null);

  useEffect(() => {
    if (selectedUser) {
      setDisplayName(selectedUser.displayName);
    }
  }, [selectedUser]);

  const usersOptions = useMemo(() => users, [users]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!file) {
      enqueueSnackbar('Select an audio file first.', { variant: 'warning' });
      return;
    }
    if (!displayName.trim()) {
      enqueueSnackbar('Display name is required.', { variant: 'warning' });
      return;
    }
    try {
      await uploadVoice.mutateAsync({
        file,
        displayName: displayName.trim(),
        userId: selectedUser?.id,
      });
      enqueueSnackbar('Voice sample uploaded', { variant: 'success' });
      setFile(null);
      setSelectedUser(null);
      setDisplayName('');
    } catch (error) {
      enqueueSnackbar((error as Error).message, { variant: 'error' });
    }
  };

  return (
    <Box>
      <PageHeader
        eyebrow="Voice diarization"
        title="Voice profiles"
        subtitle="Upload intro clips for each speaker so diarization can auto-assign tasks."
      />
      <Stack
        direction={{ xs: 'column', lg: 'row' }}
        spacing={3}
        alignItems="stretch"
      >
        <Paper
          component="form"
          onSubmit={handleSubmit}
          sx={{ p: { xs: 3, md: 4 }, flex: { lg: '0.45' } }}
        >
          <Stack spacing={2}>
            <Autocomplete
              options={usersOptions}
              value={selectedUser}
              getOptionLabel={(option) => option.displayName}
              onChange={(_event, value) =>
                setSelectedUser((value as User) ?? null)
              }
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Select existing user (optional)"
                  placeholder="Start typing a name"
                />
              )}
            />
            <TextField
              label="Display name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              required
            />
            <Stack spacing={1}>
              <Button variant="outlined" component="label">
                {file ? file.name : 'Choose audio file'}
                <input
                  type="file"
                  hidden
                  accept="audio/*"
                  onChange={(event) => {
                    const picked = event.target.files?.[0];
                    if (picked) {
                      setFile(picked);
                    }
                  }}
                />
              </Button>
              <Typography variant="caption" color="text.secondary">
                WAV, MP3, and M4A formats supported.
              </Typography>
            </Stack>
            <Stack direction="row" spacing={1}>
              <Button
                type="submit"
                variant="contained"
                disabled={uploadVoice.isPending}
                sx={{ flex: 1 }}
              >
                Upload & sync
              </Button>
              <Button
                variant="text"
                onClick={() => {
                  setSelectedUser(null);
                  setDisplayName('');
                  setFile(null);
                }}
                sx={{ flex: 1 }}
              >
                Reset
              </Button>
            </Stack>
          </Stack>
        </Paper>
        <Paper sx={{ p: { xs: 2, md: 3 }, flex: 1 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Email</TableCell>
                <TableCell>Voice sample</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {isLoading && (
                <TableRow>
                  <TableCell colSpan={3}>Loading users…</TableCell>
                </TableRow>
              )}
              {!isLoading && users.length === 0 && (
                <TableRow>
                  <TableCell colSpan={3}>
                    <Typography variant="body2" color="text.secondary">
                      No users yet. Upload a voice sample to create one.
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
              {users.map((user) => (
                <TableRow key={user.id}>
                  <TableCell>{user.displayName}</TableCell>
                  <TableCell>{user.email ?? '—'}</TableCell>
                  <TableCell>
                    {user.voiceSamplePath ? 'Uploaded' : 'Missing'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      </Stack>
    </Box>
  );
};
