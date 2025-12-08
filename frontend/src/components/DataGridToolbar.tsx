import {Badge, Box, Button, CircularProgress, MenuItem, Paper, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography,} from '@mui/material';
import type {TaskStatus} from '../types';

type StatusFilter = TaskStatus | 'all';

type DataGridToolbarProps = {
    title?: string;
    selectionCount: number;
    onApproveSelected?: () => void;
    onRejectSelected?: () => void;
    disableActions?: boolean;
    disableApprove?: boolean;
    disableReject?: boolean;
    statusFilter?: StatusFilter;
    onStatusFilterChange?: (status: StatusFilter) => void;
    search?: string;
    onSearchChange?: (value: string) => void;
    projectOptions?: Array<{value: string; label: string}>;
    projectValue?: string;
    projectError?: string;
    projectLoading?: boolean;
    onProjectChange?: (value: string) => void;
    variant?: 'card' | 'inline';
};

export const DataGridToolbar = ({
                                    title,
                                    selectionCount,
                                    onApproveSelected,
                                    onRejectSelected,
                                    disableActions,
                                    disableApprove = disableActions,
                                    disableReject = disableActions,
                                    statusFilter = 'all',
                                    onStatusFilterChange,
                                    search = '',
                                    onSearchChange,
                                    projectOptions = [],
                                    projectValue,
                                    projectError,
                                    projectLoading = false,
                                    onProjectChange,
                                    variant = 'card',
                                }: DataGridToolbarProps) => {
    const isInline = variant === 'inline';
    return (
        <Stack
            component={isInline ? 'div' : Paper}
            elevation={isInline ? undefined : 0}
            spacing={2}
            direction={{xs: 'column', md: 'row'}}
            alignItems={{xs: 'stretch', md: 'center'}}
            justifyContent="space-between"
            sx={(theme) => ({
                mb: isInline ? 2 : 3,
                p: isInline ? 0 : {xs: 2, md: 2.5},
                borderRadius: isInline ? 0 : 3,
                border: isInline ? 'none' : `1px solid ${theme.palette.divider}`,
                background: isInline
                    ? 'transparent'
                    : theme.palette.mode === 'light'
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
                    sx={{ml: title ? 1 : 0}}
                />
            </Stack>
            <Stack
                direction={{xs: 'column', md: 'row'}}
                spacing={1}
                alignItems={{xs: 'stretch', md: 'center'}}
                flexGrow={1}
                justifyContent="flex-end"
            >
                {onProjectChange && (
                    <TextField
                        select
                        size="small"
                        label="Jira project"
                        value={projectValue ?? ''}
                        onChange={(event) => onProjectChange(event.target.value)}
                        sx={{minWidth: {xs: '100%', md: 220}}}
                        disabled={projectLoading || projectOptions.length === 0}
                        error={Boolean(projectError)}
                        helperText={projectError}
                        SelectProps={{displayEmpty: true}}
                        InputProps={{
                            endAdornment: projectLoading ? (
                                <CircularProgress size={16} sx={{mr: 1}}/>
                            ) : undefined,
                        }}
                    >
                        <MenuItem value="" disabled>
                            {projectLoading ? 'Loading projects…' : 'Select a project'}
                        </MenuItem>
                        {projectOptions.map((option) => (
                            <MenuItem key={option.value} value={option.value}>
                                {option.label}
                            </MenuItem>
                        ))}
                    </TextField>
                )}
                {onSearchChange && (
                    <TextField
                        size="small"
                        placeholder="Search"
                        value={search}
                        onChange={(event) => onSearchChange(event.target.value)}
                        sx={{minWidth: {xs: '100%', md: 220}}}
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
                {(onApproveSelected || onRejectSelected) && (
                    <Box display="flex" gap={1} flexWrap="wrap">
                        {onRejectSelected && (
                            <Button
                                variant="outlined"
                                color="inherit"
                                onClick={onRejectSelected}
                                disabled={disableReject}
                            >
                                Reject
                            </Button>
                        )}
                        {onApproveSelected && (
                            <Button
                                variant="contained"
                                color="primary"
                                onClick={onApproveSelected}
                                disabled={disableApprove}
                            >
                                Approve
                            </Button>
                        )}
                    </Box>
                )}
            </Stack>
        </Stack>
    );
};
