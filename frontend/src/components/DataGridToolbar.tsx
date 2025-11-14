import {
  Badge,
  Box,
  Button,
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
    spacing={2}
    direction={{ xs: 'column', sm: 'row' }}
    alignItems={{ xs: 'stretch', sm: 'center' }}
    justifyContent="space-between"
    sx={{ mb: 2 }}
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
      direction={{ xs: 'column', sm: 'row' }}
      spacing={1}
      alignItems={{ xs: 'stretch', sm: 'center' }}
      flexGrow={1}
      justifyContent="flex-end"
    >
      {onSearchChange && (
        <TextField
          size="small"
          placeholder="Search"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
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
        <Box display="flex" gap={1}>
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
        <Box display="flex" gap={1}>
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
