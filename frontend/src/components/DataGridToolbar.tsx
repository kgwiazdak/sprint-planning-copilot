import {
  Badge,
  Box,
  Button,
  Paper,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import type { TaskStatus } from '../types';

type StatusFilter = TaskStatus | 'all';

type DataGridToolbarProps = {
  title?: string;
  selectionCount: number;
  onApproveSelected?: () => void;
  onRejectSelected?: () => void;
  onApproveAll?: () => void;
  onRejectAll?: () => void;
  disableActions?: boolean;
  statusFilter?: StatusFilter;
  onStatusFilterChange?: (status: StatusFilter) => void;
  search?: string;
  onSearchChange?: (value: string) => void;
};

export const DataGridToolbar = ({
  title,
  selectionCount,
  onApproveSelected,
  onRejectSelected,
  onApproveAll,
  onRejectAll,
  disableActions,
  statusFilter = 'all',
  onStatusFilterChange,
  search = '',
  onSearchChange,
}: DataGridToolbarProps) => (
  <Stack
    component={Paper}
    elevation={0}
    spacing={2}
    direction={{ xs: 'column', md: 'row' }}
    alignItems={{ xs: 'stretch', md: 'center' }}
    justifyContent="space-between"
    sx={(theme) => ({
      mb: 3,
      p: { xs: 2, md: 2.5 },
      borderRadius: 3,
      border: `1px solid ${theme.palette.divider}`,
      background:
        theme.palette.mode === 'light'
          ? 'linear-gradient(135deg, rgba(15,23,42,0.02), rgba(37,99,235,0.08))'
          : 'linear-gradient(135deg, rgba(15,23,42,0.85), rgba(15,118,225,0.15))',
    })}
  >
    <Stack spacing={1} direction="row" alignItems="center">
      {title && (
        <Typography variant="h6" fontWeight={600}>
          {title}
        </Typography>
      )}
      <Badge
        color="primary"
        badgeContent={selectionCount}
        invisible={selectionCount === 0}
        sx={{ ml: title ? 1 : 0 }}
      />
    </Stack>
    <Stack
      direction={{ xs: 'column', md: 'row' }}
      spacing={1}
      alignItems={{ xs: 'stretch', md: 'center' }}
      flexGrow={1}
      justifyContent="flex-end"
    >
      {onSearchChange && (
        <TextField
          size="small"
          placeholder="Search"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          sx={{ minWidth: { xs: '100%', md: 220 } }}
        />
      )}
      {onStatusFilterChange && (
        <ToggleButtonGroup
          size="small"
          exclusive
          value={statusFilter}
          onChange={(_event, value) => value && onStatusFilterChange(value)}
          color="primary"
        >
          <ToggleButton value="all">All</ToggleButton>
          <ToggleButton value="draft">Draft</ToggleButton>
          <ToggleButton value="approved">Approved</ToggleButton>
          <ToggleButton value="rejected">Rejected</ToggleButton>
        </ToggleButtonGroup>
      )}
      {(onApproveAll || onRejectAll) && (
        <Box display="flex" gap={1} flexWrap="wrap">
          {onRejectAll && (
            <Button variant="text" color="inherit" onClick={onRejectAll}>
              Reject All
            </Button>
          )}
          {onApproveAll && (
            <Button variant="text" onClick={onApproveAll}>
              Approve All
            </Button>
          )}
        </Box>
      )}
      {(onApproveSelected || onRejectSelected) && (
        <Box display="flex" gap={1} flexWrap="wrap">
          {onRejectSelected && (
            <Button
              variant="outlined"
              color="inherit"
              onClick={onRejectSelected}
              disabled={disableActions}
            >
              Reject
            </Button>
          )}
          {onApproveSelected && (
            <Button
              variant="contained"
              color="primary"
              onClick={onApproveSelected}
              disabled={disableActions}
            >
              Approve
            </Button>
          )}
        </Box>
      )}
    </Stack>
  </Stack>
);
